from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from llm_client import OllamaClient, OllamaConnectionError, OllamaTimeoutError
from session_router import verify_session_token

logger = logging.getLogger("api-gateway.websocket")
router = APIRouter()
CONV_MANAGER_URL = os.getenv("CONV_MANAGER_URL", "http://conv-manager:8001")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
WS_SEMAPHORE = asyncio.Semaphore(10)

_CM_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_CM_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
_cm_client: httpx.AsyncClient | None = None

ASR_SERVICE_WS_URL = os.getenv("ASR_SERVICE_WS_URL", "ws://asr-service:8002/ws/transcribe")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://tts-service:8003")
VOICE_SEMAPHORE = asyncio.Semaphore(4)
ALLOWED_VOICES = {"af_bella", "af_sarah", "af_nicole", "am_michael"}
DEFAULT_VOICE = "af_bella"
DEFAULT_TTS_SPEED = 1.0
MIN_TTS_SPEED = 0.25
MAX_TTS_SPEED = 3.0
_voice_state: dict[str, dict[str, Any]] = {}

_TTS_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
_tts_client: httpx.AsyncClient | None = None


@dataclass
class AsrBridge:
    websocket: Any
    reader_task: asyncio.Task
    final_text: asyncio.Future


def get_cm_client() -> httpx.AsyncClient:
    global _cm_client
    if _cm_client is None or _cm_client.is_closed:
        _cm_client = httpx.AsyncClient(timeout=_CM_TIMEOUT, limits=_CM_LIMITS)
    return _cm_client


def get_tts_client() -> httpx.AsyncClient:
    global _tts_client
    if _tts_client is None or _tts_client.is_closed:
        _tts_client = httpx.AsyncClient(timeout=_TTS_TIMEOUT)
    return _tts_client


def _get_voice_preferences(session_id: str) -> dict[str, Any]:
    return {
        "voice": DEFAULT_VOICE,
        "speed": DEFAULT_TTS_SPEED,
        "speech_enabled": True,
        **_voice_state.get(session_id, {}),
    }


def _set_voice_preferences(
    session_id: str,
    *,
    voice: str | None = None,
    speed: float | None = None,
    speech_enabled: bool | None = None,
) -> dict[str, Any]:
    prefs = _get_voice_preferences(session_id)
    if voice is not None:
        prefs["voice"] = voice if voice in ALLOWED_VOICES else DEFAULT_VOICE
    if speed is not None:
        try:
            prefs["speed"] = min(MAX_TTS_SPEED, max(MIN_TTS_SPEED, float(speed)))
        except (TypeError, ValueError):
            prefs["speed"] = DEFAULT_TTS_SPEED
    if speech_enabled is not None:
        prefs["speech_enabled"] = bool(speech_enabled)
    _voice_state[session_id] = prefs
    return prefs


async def _run_llm_pipeline(
    websocket: WebSocket,
    session_id: str,
    content: str,
    tts_enabled: bool,
) -> None:
    client = get_cm_client()
    build_resp = await client.post(
        f"{CONV_MANAGER_URL}/internal/build-prompt",
        json={"session_id": session_id, "user_message": content},
    )
    build_resp.raise_for_status()
    build_data = build_resp.json()

    if build_data.get("blocked"):
        await websocket.send_text(
            json.dumps({"type": "error", "content": build_data.get("block_reason")})
        )
        return

    prompt = build_data.get("prompt")
    assistant_response = ""
    response_id = uuid.uuid4().hex
    token_count = 0
    sentence_buf = ""
    tts_enabled = tts_enabled and bool(_get_voice_preferences(session_id).get("speech_enabled", True))
    tts_queue: asyncio.Queue | None = asyncio.Queue() if tts_enabled else None
    tts_sender_task = (
        asyncio.create_task(_stream_tts_audio(websocket, response_id, tts_queue))
        if tts_queue is not None
        else None
    )
    llm = OllamaClient(base_url=OLLAMA_URL)

    try:
        async for token in llm.generate(prompt=prompt):
            token_count += 1
            assistant_response += token
            await websocket.send_text(
                json.dumps({"type": "token", "content": token, "response_id": response_id})
            )

            if tts_enabled:
                sentence_buf += token
                if re.search(r"[.!?]\s", sentence_buf):
                    parts = re.split(r"(?<=[.!?])\s", sentence_buf, maxsplit=1)
                    sentence_to_speak = parts[0].strip()
                    sentence_buf = parts[1] if len(parts) > 1 else ""
                    await _queue_tts_sentence(tts_queue, session_id, sentence_to_speak)
    except (OllamaConnectionError, OllamaTimeoutError):
        if tts_queue is not None:
            await tts_queue.put(None)
        if tts_sender_task is not None:
            await tts_sender_task
        await websocket.send_text(json.dumps({"type": "error", "content": "internal_error"}))
        return

    if token_count == 0:
        assistant_response = (
            "I can help with orders, shipping, returns, warranty, and account FAQs. "
            "Please share your order ID if this is an order-specific request."
        )
        await websocket.send_text(
            json.dumps({"type": "token", "content": assistant_response, "response_id": response_id})
        )

    if tts_enabled and sentence_buf.strip():
        await _queue_tts_sentence(tts_queue, session_id, sentence_buf.strip())

    if tts_queue is not None:
        await tts_queue.put(None)
    if tts_sender_task is not None:
        await tts_sender_task

    await client.post(
        f"{CONV_MANAGER_URL}/internal/update-history",
        json={"session_id": session_id, "role": "user", "content": content},
    )
    await client.post(
        f"{CONV_MANAGER_URL}/internal/update-history",
        json={"session_id": session_id, "role": "assistant", "content": assistant_response},
    )
    await websocket.send_text(json.dumps({"type": "done", "content": "", "response_id": response_id}))


async def _queue_tts_sentence(
    tts_queue: asyncio.Queue | None,
    session_id: str,
    sentence: str,
) -> None:
    if tts_queue is None or not sentence:
        return
    await tts_queue.put(asyncio.create_task(_synthesize(session_id, sentence)))


async def _stream_tts_audio(
    websocket: WebSocket,
    response_id: str,
    tts_queue: asyncio.Queue,
) -> None:
    while True:
        task = await tts_queue.get()
        if task is None:
            return
        try:
            audio_bytes = await task
        except Exception:
            audio_bytes = None
        if isinstance(audio_bytes, bytes) and audio_bytes:
            await websocket.send_text(json.dumps({"type": "audio_segment", "response_id": response_id}))
            await websocket.send_bytes(audio_bytes)


async def _synthesize(session_id: str, text: str) -> bytes | None:
    """Synthesize text to WAV bytes. Returns None on failure."""
    try:
        preferences = _get_voice_preferences(session_id)
        tts_client = get_tts_client()
        response = await tts_client.post(
            f"{TTS_SERVICE_URL}/synthesize",
            json={
                "text": text,
                "voice": preferences["voice"],
                "speed": preferences["speed"],
            },
        )
        if response.status_code != 200:
            return None
        return response.content if response.content else None
    except Exception:
        return None


async def _read_asr_messages(
    upstream_websocket: WebSocket,
    downstream_websocket,
    final_text_future: asyncio.Future,
) -> None:
    try:
        async for raw_message in downstream_websocket:
            if isinstance(raw_message, bytes):
                continue

            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            message_type = payload.get("type")
            text = str(payload.get("text") or payload.get("content") or "")

            if message_type == "asr_partial":
                await upstream_websocket.send_text(json.dumps({"type": "asr_partial", "content": text}))
            elif message_type == "asr_final":
                if not final_text_future.done():
                    final_text_future.set_result(text)
                await upstream_websocket.send_text(json.dumps({"type": "asr_final", "content": text}))
            elif message_type == "asr_error":
                if not final_text_future.done():
                    final_text_future.set_result("")
                await upstream_websocket.send_text(json.dumps({"type": "error", "content": "asr_unavailable"}))
    except websockets.ConnectionClosed:
        if not final_text_future.done():
            final_text_future.set_result("")
    except Exception:
        logger.exception("action=asr_bridge_read_failed")
        if not final_text_future.done():
            final_text_future.set_result("")
        try:
            await upstream_websocket.send_text(json.dumps({"type": "error", "content": "asr_unavailable"}))
        except Exception:
            pass


async def _open_asr_bridge(upstream_websocket: WebSocket) -> AsrBridge | None:
    if VOICE_SEMAPHORE.locked():
        await upstream_websocket.send_text(json.dumps({"type": "error", "content": "voice_at_capacity"}))
        return None

    await VOICE_SEMAPHORE.acquire()
    try:
        downstream_websocket = await websockets.connect(
            ASR_SERVICE_WS_URL, max_size=None, open_timeout=10, close_timeout=5,
        )
    except Exception:
        VOICE_SEMAPHORE.release()
        await upstream_websocket.send_text(json.dumps({"type": "error", "content": "asr_unavailable"}))
        return None

    final_text = asyncio.get_running_loop().create_future()
    reader_task = asyncio.create_task(_read_asr_messages(upstream_websocket, downstream_websocket, final_text))
    return AsrBridge(websocket=downstream_websocket, reader_task=reader_task, final_text=final_text)


async def _close_asr_bridge(bridge: AsrBridge | None) -> None:
    if bridge is None:
        return

    try:
        await bridge.websocket.close()
    except Exception:
        pass
    try:
        await bridge.reader_task
    except Exception:
        pass
    VOICE_SEMAPHORE.release()


@router.websocket("/ws/chat/{session_id}")
async def chat_ws(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=""),
) -> None:
    if not token or not verify_session_token(session_id, token):
        await websocket.accept()
        await websocket.send_json({"type": "error", "content": "unauthorized"})
        await websocket.close(code=4401)
        return

    if WS_SEMAPHORE.locked():
        await websocket.accept()
        await websocket.send_json({"type": "error", "content": "server_at_capacity"})
        await websocket.close()
        return

    await WS_SEMAPHORE.acquire()
    await websocket.accept()
    logger.info("session_id=%s connected", session_id)

    asr_bridge: AsrBridge | None = None

    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                break

            text_message = data.get("text")
            if text_message:
                try:
                    payload = json.loads(text_message)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"type": "error", "content": "internal_error"}))
                    continue

                message_type = payload.get("type")

                if message_type == "set_voice":
                    prefs = _set_voice_preferences(session_id, voice=payload.get("voice", DEFAULT_VOICE))
                    await websocket.send_text(
                        json.dumps({
                            "type": "voice_preferences_set",
                            "voice": prefs["voice"],
                            "speed": prefs["speed"],
                            "speech_enabled": prefs["speech_enabled"],
                        })
                    )
                    continue

                if message_type == "set_voice_preferences":
                    prefs = _set_voice_preferences(
                        session_id,
                        voice=payload.get("voice"),
                        speed=payload.get("speed"),
                        speech_enabled=payload.get("speech_enabled"),
                    )
                    await websocket.send_text(
                        json.dumps({
                            "type": "voice_preferences_set",
                            "voice": prefs["voice"],
                            "speed": prefs["speed"],
                            "speech_enabled": prefs["speech_enabled"],
                        })
                    )
                    continue

                if message_type == "audio_start":
                    if asr_bridge is None:
                        asr_bridge = await _open_asr_bridge(websocket)
                    continue

                if message_type == "audio_end":
                    if asr_bridge is None:
                        await websocket.send_text(json.dumps({"type": "done", "content": ""}))
                        continue

                    try:
                        await asr_bridge.websocket.send(json.dumps({"type": "audio_end"}))
                        final_text = await asyncio.wait_for(asr_bridge.final_text, timeout=30)
                    except (asyncio.TimeoutError, Exception) as exc:
                        logger.warning("session_id=%s asr_bridge_error=%s", session_id, type(exc).__name__)
                        final_text = ""

                    await _close_asr_bridge(asr_bridge)
                    asr_bridge = None

                    if final_text.strip():
                        await _run_llm_pipeline(websocket, session_id, final_text, tts_enabled=True)
                    else:
                        await websocket.send_text(json.dumps({"type": "done", "content": ""}))
                    continue

                if message_type != "user_message":
                    await websocket.send_text(json.dumps({"type": "error", "content": "internal_error"}))
                    continue

                user_message = str(payload.get("content", "")).strip()
                if not user_message:
                    await websocket.send_text(json.dumps({"type": "done", "content": ""}))
                    continue
                await _run_llm_pipeline(websocket, session_id, user_message, tts_enabled=True)
                continue

            audio_bytes = data.get("bytes")
            if audio_bytes is None:
                continue

            if asr_bridge is None:
                await websocket.send_text(json.dumps({"type": "error", "content": "audio_not_started"}))
                continue

            await asr_bridge.websocket.send(audio_bytes)

    except WebSocketDisconnect:
        logger.info("session_id=%s disconnected", session_id)
    except Exception as exc:
        logger.exception("session_id=%s error=%s", session_id, type(exc).__name__)
        try:
            await websocket.send_text(json.dumps({"type": "error", "content": "internal_error"}))
        except Exception:
            pass
    finally:
        await _close_asr_bridge(asr_bridge)
        _voice_state.pop(session_id, None)
        WS_SEMAPHORE.release()
