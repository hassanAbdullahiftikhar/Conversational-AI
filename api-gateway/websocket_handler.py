from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

from llm_client import LlmClient, LlmConnectionError, get_llm_http_client
from session_router import verify_session_token
from eval_state import track_tool_calls, clear_tracked_tool_calls

logger = logging.getLogger("api-gateway.websocket")
router = APIRouter()
CONV_MANAGER_URL = os.getenv("CONV_MANAGER_URL", "http://localhost:8001")
LLM_URL = os.getenv("LLM_URL", "http://localhost:11434")
WS_SEMAPHORE = asyncio.Semaphore(10)

_CM_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_CM_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
_cm_client: httpx.AsyncClient | None = None

ASR_SERVICE_WS_URL = os.getenv("ASR_SERVICE_WS_URL", "ws://asr-service:8002/ws/transcribe")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://tts-service:8003")
TOOL_ROUTER_ENABLED = os.getenv("TOOL_ROUTER_ENABLED", "true").lower() in {"1", "true", "yes"}
TOOL_ROUTER_URL = f"{CONV_MANAGER_URL}/internal/tool-router/execute"
TOOL_TIMEOUT_SECONDS = float(os.getenv("TOOL_TIMEOUT_SECONDS", "15.0"))
TOOL_MAX_RETRIES = int(os.getenv("TOOL_MAX_RETRIES", "1"))
MAX_MULTI_TOOLS = int(os.getenv("MAX_MULTI_TOOLS", "3"))
ALLOWED_VOICES = {"af_bella", "af_sarah", "af_nicole", "am_michael"}
DEFAULT_VOICE = "af_bella"
DEFAULT_TTS_SPEED = 1.0
MIN_TTS_SPEED = 0.5
MAX_TTS_SPEED = 2.0
_voice_state: dict[str, dict[str, Any]] = {}

_TTS_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
_tts_client: httpx.AsyncClient | None = None
_ws_locks: dict[str, asyncio.Lock] = {}
_session_voice_locks: dict[str, asyncio.Semaphore] = {}
_replay_in_progress: dict[str, asyncio.Lock] = {}
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_TOOL_TAG_RE = re.compile(r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


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


def _get_ws_lock(session_id: str) -> asyncio.Lock:
    lock = _ws_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _ws_locks[session_id] = lock
    return lock


def _get_replay_lock(session_id: str) -> asyncio.Lock:
    lock = _replay_in_progress.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _replay_in_progress[session_id] = lock
    return lock


def _get_session_voice_semaphore(session_id: str) -> asyncio.Semaphore:
    if session_id not in _session_voice_locks:
        _session_voice_locks[session_id] = asyncio.Semaphore(1)
    return _session_voice_locks[session_id]


async def _ws_send_text(websocket: WebSocket, session_id: str, payload: dict[str, Any]) -> None:
    async with _get_ws_lock(session_id):
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))


async def _ws_send_json(websocket: WebSocket, session_id: str, payload: dict[str, Any]) -> None:
    async with _get_ws_lock(session_id):
        await websocket.send_json(payload)


async def _ws_send_bytes(websocket: WebSocket, session_id: str, payload: bytes) -> None:
    async with _get_ws_lock(session_id):
        await websocket.send_bytes(payload)


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


def _extract_balanced_json_object(text: str) -> str | None:
    in_string = False
    escaped = False
    depth = 0
    start = -1

    for idx, char in enumerate(text):
        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : idx + 1]

    return None


def _normalize_tool_call(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload
    if isinstance(data.get("tool_call"), dict):
        data = data["tool_call"]

    tool_name = data.get("tool") or data.get("name") or data.get("tool_name")
    if not tool_name:
        return None

    arguments = data.get("arguments") or data.get("args") or data.get("input") or {}
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                arguments = parsed
        except json.JSONDecodeError:
            arguments = {"raw": arguments}

    if not isinstance(arguments, dict):
        return None

    call_id = data.get("call_id") or data.get("id") or uuid.uuid4().hex
    return {
        "tool": str(tool_name),
        "tool_name": str(tool_name),
        "arguments": arguments,
        "args": arguments,
        "call_id": str(call_id),
    }


def _extract_tool_call(text: str) -> dict[str, Any] | None:
    candidates: list[str] = []

    for match in _JSON_FENCE_RE.finditer(text):
        candidates.append(match.group(1))

    for match in _TOOL_TAG_RE.finditer(text):
        candidates.append(match.group(1))

    balanced = _extract_balanced_json_object(text)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        # Only treat as tool call if it has expected tool call structure
        normalized = _normalize_tool_call(parsed)
        if normalized is not None:
            # Additional validation: tool call JSON should have specific keys
            if "tool" in normalized or "name" in parsed or "tool_name" in parsed:
                return normalized

    return None


def _extract_tool_calls(text: str) -> list[dict[str, Any]]:
    """
    Extract ALL valid tool calls from text.
    Handles array format [{}], separate JSON blocks, and tool tags.
    Returns up to MAX_MULTI_TOOLS (default 3) tools.
    """
    tools: list[dict[str, Any]] = []

    # 1. Try to extract array format: [{"tool": "A"}, {"tool": "B"}]
    array_match = re.search(r"\[\s*(\{[\s\S]*\})\s*\]", text)
    if array_match:
        try:
            array_content = "[" + array_match.group(1) + "]"
            parsed = json.loads(array_content)
            if isinstance(parsed, list):
                for item in parsed[:MAX_MULTI_TOOLS]:
                    if isinstance(item, dict):
                        normalized = _normalize_tool_call(item)
                        if normalized and normalized not in tools:
                            if "tool" in item or "name" in item or "tool_name" in item:
                                tools.append(normalized)
        except (json.JSONDecodeError, ValueError):
            pass

    # 2. Extract from fenced JSON blocks: ```json{...}``` ```json{...}```
    for match in _JSON_FENCE_RE.finditer(text):
        raw = match.group(1)
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                normalized = _normalize_tool_call(parsed)
                if normalized and normalized not in tools:
                    tools.append(normalized)
        except json.JSONDecodeError:
            pass
        if len(tools) >= MAX_MULTI_TOOLS:
            break

    # 3. Extract from tool tags: <tool_call>{...}</tool_call>
    for match in _TOOL_TAG_RE.finditer(text):
        raw = match.group(1)
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                normalized = _normalize_tool_call(parsed)
                if normalized and normalized not in tools:
                    tools.append(normalized)
        except json.JSONDecodeError:
            pass
        if len(tools) >= MAX_MULTI_TOOLS:
            break

    # 4. Extract balanced JSON objects (for JSON without fences)
    pos = 0
    in_string = False
    escaped = False
    depth = 0
    start = -1
    while pos < len(text) and len(tools) < MAX_MULTI_TOOLS:
        char = text[pos]
        if escaped:
            escaped = False
            pos += 1
            continue
        if char == "\\":
            escaped = True
            pos += 1
            continue
        if char == '"':
            in_string = not in_string
            pos += 1
            continue
        if in_string:
            pos += 1
            continue
        if char == "{":
            if depth == 0:
                start = pos
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : pos + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        normalized = _normalize_tool_call(parsed)
                        if normalized and normalized not in tools:
                            # Only accept if it has tool call structure
                            if "tool" in parsed or "name" in parsed or "tool_name" in parsed:
                                tools.append(normalized)
                except json.JSONDecodeError:
                    pass
                start = -1
        pos += 1

    return tools


def _looks_like_tool_call(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return True
    # If it starts with typical tool-call prefixes, it might be a tool call.
    if stripped[0] in {'{', '<', '`'}:
        return True
    # Give the model a longer prefix window before deciding this is plain text.
    # Short responses are more likely to be direct answers, not tool calls.
    if len(stripped) < 1000:
        return True
    if "```" in stripped or "<tool" in stripped.lower():
        return True
    return False


def _normalize_replay_text(text: str) -> str:
    cleaned = text.replace("**", "").replace("__", "").replace("`", "")
    cleaned = _MARKDOWN_LINK_RE.sub(r"\1", cleaned)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


async def _execute_tool_call(session_id: str, tool_call: dict[str, Any]) -> dict[str, Any]:
    client = get_cm_client()
    tool_name = str(tool_call.get("tool") or "")
    call_id = str(tool_call.get("call_id") or uuid.uuid4().hex)

    for attempt in range(TOOL_MAX_RETRIES + 1):
        try:
            response = await client.post(
                TOOL_ROUTER_URL,
                json={
                    "session_id": session_id,
                    "tool": tool_name,
                    "arguments": tool_call.get("arguments") or {},
                    "call_id": call_id,
                },
                timeout=httpx.Timeout(TOOL_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return {
                "ok": False,
                "tool": tool_name,
                "call_id": call_id,
                "error": {
                    "code": "invalid_tool_response",
                    "message": "Tool router returned a non-object payload.",
                    "retryable": False,
                },
            }
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt < TOOL_MAX_RETRIES:
                continue
            return {
                "ok": False,
                "tool": tool_name,
                "call_id": call_id,
                "error": {
                    "code": "tool_timeout",
                    "message": f"Tool request failed after retry policy ({type(exc).__name__}).",
                    "retryable": True,
                },
            }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "tool": tool_name,
                "call_id": call_id,
                "error": {
                    "code": "tool_router_http_error",
                    "message": f"Tool router HTTP error: {type(exc).__name__}",
                    "retryable": False,
                },
            }

    return {
        "ok": False,
        "tool": tool_name,
        "call_id": call_id,
        "error": {
            "code": "tool_unknown_failure",
            "message": "Tool execution failed unexpectedly.",
            "retryable": False,
        },
    }


async def _replay_assistant_message(websocket: WebSocket, session_id: str, content: str) -> None:
    replay_lock = _get_replay_lock(session_id)
    if replay_lock.locked():
        return

    async with replay_lock:
        replay_text = _normalize_replay_text(content)
        if not replay_text:
            await _ws_send_text(websocket, session_id, {"type": "error", "content": "replay_empty"})
            return

        response_id = f"replay-{uuid.uuid4().hex}"
        await _ws_send_text(websocket, session_id, {"type": "audio_segment", "response_id": response_id})
        audio_bytes, _synthesis_ms = await _synthesize(session_id, replay_text)
        if not isinstance(audio_bytes, bytes) or not audio_bytes:
            await _ws_send_text(websocket, session_id, {"type": "error", "content": "replay_unavailable"})
            return

        await _ws_send_bytes(websocket, session_id, audio_bytes)


def _render_tool_context(tool_result: dict[str, Any]) -> str:
    if bool(tool_result.get("ok")):
        tool_name = str(tool_result.get("tool", "tool"))
        result_payload = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
        return (
            f"Tool execution result for '{tool_name}' (call_id={tool_result.get('call_id', '')}):\n"
            + json.dumps(result_payload, ensure_ascii=False)
        )

    error = tool_result.get("error") if isinstance(tool_result.get("error"), dict) else {}
    return (
        f"Tool execution failed (call_id={tool_result.get('call_id', '')}): "
        f"{error.get('code', 'unknown_error')} - {error.get('message', 'no message')}"
    )


def _render_multi_tool_context(
    tool_results: list[dict[str, Any]], max_tokens: int = 800
) -> str:
    if not tool_results:
        return ""
    if len(tool_results) == 1:
        return _render_tool_context(tool_results[0])

    outputs: list[str] = []
    for i, result in enumerate(tool_results, 1):
        tool_name = str(result.get("tool", "unknown"))
        if bool(result.get("ok")):
            result_payload = result.get("result") if isinstance(result.get("result"), dict) else {}
            outputs.append(
                f"[{i}] {tool_name} result:\n{json.dumps(result_payload, ensure_ascii=False)}"
            )
        else:
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            outputs.append(
                f"[{i}] {tool_name} FAILED: {error.get('code', 'unknown')} - {error.get('message', 'error')}"
            )

    combined = "\n\n".join(outputs)
    if len(combined) > max_tokens * 4:
        combined = combined[: max_tokens * 4]
    return combined


def _coerce_chat_messages(raw_chat_messages: Any) -> list[dict[str, str]]:
    chat_messages: list[dict[str, str]] = []
    if not isinstance(raw_chat_messages, list):
        return chat_messages

    for item in raw_chat_messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        message_content = str(item.get("content") or "").strip()
        if not role or not message_content:
            continue
        chat_messages.append({"role": role, "content": message_content})

    return chat_messages


async def _stream_with_tool_interception(
    *,
    llm: LlmClient,
    session_id: str,
    prompt: str,
    messages: list[dict[str, str]],
    emit_token: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    passthrough = not TOOL_ROUTER_ENABLED
    planner_buffer = ""

    async for token in llm.stream(prompt=prompt, messages=messages):
        if passthrough:
            await emit_token(token)
            continue

        planner_buffer += token
        has_json_markers = "```" in planner_buffer or "<tool_call" in planner_buffer.lower()
        
        # DEBUG: Log all tokens for evaluations
        if os.getenv("EVAL_MODE") == "true":
            logger.info("session_id=%s token_received=%s buffer_len=%d", session_id, token, len(planner_buffer))

        if not _looks_like_tool_call(planner_buffer) and not has_json_markers:
            logger.info("session_id=%s action=passthrough reason=no_markers_found buffer=%s", "eval", repr(planner_buffer))
            passthrough = True
            await emit_token(planner_buffer)
            planner_buffer = ""
            continue

        if len(planner_buffer) >= 1800:
            # Try to parse as JSON before deciding to passthrough
            has_valid_json = False
            try:
                json.loads(planner_buffer)
                has_valid_json = True
            except (json.JSONDecodeError, ValueError):
                pass
            has_closing_delimiter = "```" in planner_buffer or "</tool_call>" in planner_buffer.lower()
            if not (has_valid_json or has_closing_delimiter):
                passthrough = True
                await emit_token(planner_buffer)
                planner_buffer = ""
                continue

            if not _extract_tool_calls(planner_buffer):
                passthrough = True
                await emit_token(planner_buffer)
                planner_buffer = ""
                continue

    stream_metrics = dict(llm.last_stream_metrics)
    stream_mode = llm.last_stream_mode

    if passthrough:
        return [], stream_metrics, stream_mode

    tool_calls = _extract_tool_calls(planner_buffer)
    if not tool_calls:
        await emit_token(planner_buffer)
        return [], stream_metrics, stream_mode

    return tool_calls, stream_metrics, stream_mode


async def _run_llm_pipeline(
    websocket: WebSocket,
    session_id: str,
    content: str,
    tts_enabled: bool,
) -> None:
    pipeline_start = time.perf_counter()
    client = get_cm_client()
    logger.info("action=llm_pipeline_stage session_id=%s stage=build_prompt_request", session_id)
    prompt_build_start = time.perf_counter()
    build_resp = await client.post(
        f"{CONV_MANAGER_URL}/internal/build-prompt",
        json={"session_id": session_id, "user_message": content},
    )
    prompt_build_ms = int((time.perf_counter() - prompt_build_start) * 1000)
    build_resp.raise_for_status()
    build_data = build_resp.json()
    logger.info("session_id=%s build_data_received blocked=%s reason=%s", session_id, build_data.get("blocked"), build_data.get("block_reason"))

    if build_data.get("blocked"):
        await _ws_send_text(websocket, session_id, {"type": "error", "content": build_data.get("block_reason")})
        return

    prompt = str(build_data.get("prompt") or "")
    chat_messages = _coerce_chat_messages(build_data.get("chat_messages"))

    slot_budget = build_data.get("slot_budget") if isinstance(build_data.get("slot_budget"), dict) else {}
    token_usage_estimate = (
        build_data.get("token_usage_estimate") if isinstance(build_data.get("token_usage_estimate"), dict) else {}
    )

    assistant_response = ""
    response_id = uuid.uuid4().hex
    token_count = 0
    first_token_ms: int | None = None
    sentence_buf = ""
    logger.info("action=llm_pipeline_stage session_id=%s stage=voice_prefs", session_id)
    tts_enabled = tts_enabled and bool(_get_voice_preferences(session_id).get("speech_enabled", True))
    tts_queue: asyncio.Queue | None = asyncio.Queue(maxsize=10) if tts_enabled else None
    logger.info("action=llm_pipeline_stage session_id=%s stage=tts_task_init enabled=%s", session_id, tts_queue is not None)
    tts_sender_task = (
        asyncio.create_task(_stream_tts_audio(websocket, session_id, response_id, tts_queue))
        if tts_queue is not None
        else None
    )
    logger.info("action=llm_pipeline_stage session_id=%s stage=llm_client_init", session_id)
    shared_client = await get_llm_http_client()
    llm = LlmClient(base_url=LLM_URL, _shared_client=shared_client)
    llm_stream_start = time.perf_counter()
    timings: dict[str, Any] = {"prompt_build_ms": prompt_build_ms}
    if slot_budget:
        timings["slot_total_tokens"] = int(slot_budget.get("total") or 0)
        timings["slot_history_tokens"] = int(slot_budget.get("history") or 0)
    if token_usage_estimate:
        timings["token_estimate_history"] = int(token_usage_estimate.get("history") or 0)
        timings["token_estimate_user"] = int(token_usage_estimate.get("user") or 0)

    planner_metrics: dict[str, Any] = {}
    tool_router_used = False
    response_sources: list[dict[str, str]] = []
    tts_cleanup_done = False

    async def _finalize_tts() -> None:
        nonlocal tts_cleanup_done
        if tts_cleanup_done:
            return
        if tts_queue is not None:
            try:
                await tts_queue.put(None)
            except Exception:
                pass
        if tts_sender_task is not None:
            try:
                tts_metrics = await tts_sender_task
                if isinstance(tts_metrics, dict):
                    timings.update(tts_metrics)
            except Exception:
                pass
        tts_cleanup_done = True

    async def _emit_user_visible_token(token_chunk: str) -> None:
        nonlocal first_token_ms, token_count, assistant_response, sentence_buf

        if not token_chunk:
            return

        if first_token_ms is None:
            first_token_ms = int((time.perf_counter() - llm_stream_start) * 1000)

        token_count += 1
        assistant_response += token_chunk
        await _ws_send_text(websocket, session_id, {"type": "token", "content": token_chunk, "response_id": response_id})

        if not tts_enabled:
            return

        sentence_buf += token_chunk
        while re.search(r"[.!?]\s", sentence_buf):
            parts = re.split(r"(?<=[.!?])\s", sentence_buf, maxsplit=1)
            sentence_to_speak = parts[0].strip()
            sentence_buf = parts[1] if len(parts) > 1 else ""
            await _queue_tts_sentence(tts_queue, session_id, sentence_to_speak)

    try:
        logger.info("action=llm_pipeline_stage session_id=%s stage=llm_stream_start", session_id)
        tool_calls, planner_metrics, planner_mode = await _stream_with_tool_interception(
            llm=llm,
            session_id=session_id,
            prompt=prompt,
            messages=chat_messages,
            emit_token=_emit_user_visible_token,
        )
        if tool_calls:
            track_tool_calls(session_id, tool_calls)
        timings["planner_stream_mode"] = planner_mode

        if tool_calls:
            tool_router_used = True
            timings["tool_name"] = str(tool_calls[0].get("tool") or "")

            all_tool_results: list[dict[str, Any]] = []
            for idx, single_tool_call in enumerate(tool_calls):
                tool_exec_start = time.perf_counter()
                tool_result = await _execute_tool_call(session_id=session_id, tool_call=single_tool_call)
                timings[f"tool_exec_ms_{idx}"] = int((time.perf_counter() - tool_exec_start) * 1000)
                timings[f"tool_ok_{idx}"] = bool(tool_result.get("ok"))
                all_tool_results.append(tool_result)

            first_tool = str(tool_calls[0].get("tool", ""))
            if all(r.get("ok") for r in all_tool_results) and first_tool == "search_docs":
                for tool_result in all_tool_results:
                    if str(tool_result.get("tool", "")) == "search_docs":
                        tool_payload = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else {}
                        citations = tool_payload.get("citations") if isinstance(tool_payload.get("citations"), list) else []
                        seen_pairs: set[tuple[str, str]] = set()
                        compact_sources: list[dict[str, str]] = []
                        for citation in citations:
                            if not isinstance(citation, dict):
                                continue
                            source = str(citation.get("source") or "")
                            path = str(citation.get("path") or "")
                            title = str(citation.get("title") or "")
                            key = (source, path)
                            if not source or not path or key in seen_pairs:
                                continue
                            seen_pairs.add(key)
                            compact_sources.append({"source": source, "path": path, "title": title})
                            if len(compact_sources) >= 5:
                                break
                        response_sources = compact_sources
                        break

            tool_context = _render_multi_tool_context(all_tool_results)

            followup_build_start = time.perf_counter()
            followup_build_resp = await client.post(
                f"{CONV_MANAGER_URL}/internal/build-prompt",
                json={
                    "session_id": session_id,
                    "user_message": content,
                    "tool_context": tool_context,
                },
            )
            timings["tool_followup_prompt_build_ms"] = int(
                (time.perf_counter() - followup_build_start) * 1000
            )
            followup_build_resp.raise_for_status()
            followup_data = followup_build_resp.json()

            if followup_data.get("blocked"):
                await _emit_user_visible_token(
                    "I couldn't complete that lookup right now, but I can still help with general guidance."
                )
            else:
                followup_prompt = str(followup_data.get("prompt") or prompt)
                followup_chat_messages = _coerce_chat_messages(followup_data.get("chat_messages"))
                followup_stream_start = time.perf_counter()
                followup_tool_calls, _followup_metrics, followup_mode = await _stream_with_tool_interception(
                    llm=llm,
                    session_id=session_id,
                    prompt=followup_prompt,
                    messages=followup_chat_messages,
                    emit_token=_emit_user_visible_token,
                )
                timings["tool_followup_stream_ms"] = int(
                    (time.perf_counter() - followup_stream_start) * 1000
                )
                timings["tool_followup_stream_mode"] = followup_mode

                if followup_tool_calls and len(followup_tool_calls) > 0:
                    followup_tool_call = followup_tool_calls[0]
                    timings["tool_followup_name"] = str(followup_tool_call.get("tool") or "")
                    chained_tool_exec_start = time.perf_counter()
                    chained_tool_result = await _execute_tool_call(session_id=session_id, tool_call=followup_tool_call)
                    timings["tool_followup_exec_ms"] = int((time.perf_counter() - chained_tool_exec_start) * 1000)
                    chained_tool_context = _render_tool_context(chained_tool_result)

                    chained_followup_resp = await client.post(
                        f"{CONV_MANAGER_URL}/internal/build-prompt",
                        json={
                            "session_id": session_id,
                            "user_message": content,
                            "tool_context": chained_tool_context,
                        },
                    )
                    chained_followup_resp.raise_for_status()
                    chained_followup_data = chained_followup_resp.json()
                    if chained_followup_data.get("blocked"):
                        await _emit_user_visible_token(
                            "I couldn't complete that lookup right now, but I can still help with general guidance."
                        )
                    else:
                        chained_prompt = str(chained_followup_data.get("prompt") or followup_prompt)
                        chained_messages = _coerce_chat_messages(chained_followup_data.get("chat_messages"))
                        await _stream_with_tool_interception(
                            llm=llm,
                            prompt=chained_prompt,
                            messages=chained_messages,
                            emit_token=_emit_user_visible_token,
                        )

    except (LlmConnectionError, httpx.HTTPError) as exc:
        msg = str(exc)
        logger.warning("action=model_stream_failure detail=%s", msg)
        if "unknown model architecture" in msg.lower():
            await _ws_send_text(websocket, session_id, {"type": "error", "content": "model_unsupported_architecture"})
        else:
            await _ws_send_text(websocket, session_id, {"type": "error", "content": "internal_error"})
        await _finalize_tts()
        return

    try:
        timings["ttft_ms"] = first_token_ms if first_token_ms is not None else 0
        timings["llm_stream_wall_ms"] = int((time.perf_counter() - llm_stream_start) * 1000)
        timings["llm_stream_mode"] = llm.last_stream_mode
        llm_metrics = llm.last_stream_metrics
        if llm_metrics:
            timings.update({
                "model_prompt_tokens": llm_metrics.get("prompt_tokens", 0),
                "model_completion_tokens": llm_metrics.get("completion_tokens", 0),
                "model_total_tokens": llm_metrics.get("total_tokens", 0),
            })
        if tool_router_used and planner_metrics:
            timings.update({
                "planner_model_prompt_tokens": planner_metrics.get("prompt_tokens", 0),
                "planner_model_completion_tokens": planner_metrics.get("completion_tokens", 0),
                "planner_model_total_tokens": planner_metrics.get("total_tokens", 0),
            })

        if token_count == 0:
            assistant_response = (
                "I can help you troubleshoot and configure your smart home devices, "
                "including Home Assistant, Zigbee, and ESPHome setups."
            )
            await _ws_send_text(websocket, session_id, {"type": "token", "content": assistant_response, "response_id": response_id})

        if tts_enabled and sentence_buf.strip():
            await _queue_tts_sentence(tts_queue, session_id, sentence_buf.strip())

        await _finalize_tts()

        history_update_start = time.perf_counter()

        await client.post(
            f"{CONV_MANAGER_URL}/internal/update-history",
            json={"session_id": session_id, "role": "user", "content": content},
        )
        await client.post(
            f"{CONV_MANAGER_URL}/internal/update-history",
            json={"session_id": session_id, "role": "assistant", "content": assistant_response},
        )
        timings["history_update_ms"] = int((time.perf_counter() - history_update_start) * 1000)
        timings["pipeline_wall_ms"] = int((time.perf_counter() - pipeline_start) * 1000)
        logger.info("session_id=%s response_id=%s timings=%s", session_id, response_id, timings)
        await _ws_send_text(
            websocket,
            session_id,
            {
                "type": "done",
                "content": "",
                "response_id": response_id,
                "timings": timings,
                "sources": response_sources,
            },
        )
    finally:
        await _finalize_tts()


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
    session_id: str,
    response_id: str,
    tts_queue: asyncio.Queue,
) -> dict[str, int]:
    synthesis_ms_total = 0
    synthesis_calls = 0
    audio_segments = 0
    audio_bytes_total = 0

    while True:
        task = await tts_queue.get()
        if task is None:
            return {
                "tts_synthesis_ms": synthesis_ms_total,
                "tts_synthesis_calls": synthesis_calls,
                "tts_audio_segments": audio_segments,
                "tts_audio_bytes": audio_bytes_total,
            }

        try:
            audio_bytes, synthesis_ms = await task
            synthesis_ms_total += synthesis_ms
            synthesis_calls += 1
        except Exception:
            audio_bytes = None
            synthesis_calls += 1

        if isinstance(audio_bytes, bytes) and audio_bytes:
            await _ws_send_text(websocket, session_id, {"type": "audio_segment", "response_id": response_id})
            await _ws_send_bytes(websocket, session_id, audio_bytes)
            audio_segments += 1
            audio_bytes_total += len(audio_bytes)


async def _synthesize(session_id: str, text: str) -> tuple[bytes | None, int]:
    """Synthesize text to WAV bytes and return `(audio_bytes, synthesis_ms)`."""
    synth_start = time.perf_counter()
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
        synthesis_ms = int((time.perf_counter() - synth_start) * 1000)
        if response.status_code != 200:
            return None, synthesis_ms
        return (response.content if response.content else None), synthesis_ms
    except Exception:
        synthesis_ms = int((time.perf_counter() - synth_start) * 1000)
        return None, synthesis_ms


async def _read_asr_messages(
    upstream_websocket: WebSocket,
    session_id: str,
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
                await _ws_send_text(upstream_websocket, session_id, {"type": "asr_partial", "content": text})
            elif message_type == "asr_final":
                if not final_text_future.done():
                    final_text_future.set_result(text)
                await _ws_send_text(upstream_websocket, session_id, {"type": "asr_final", "content": text})
            elif message_type == "asr_error":
                if not final_text_future.done():
                    final_text_future.set_result("")
                await _ws_send_text(upstream_websocket, session_id, {"type": "error", "content": "asr_unavailable"})
    except websockets.ConnectionClosed:
        if not final_text_future.done():
            final_text_future.set_result("")
    except Exception:
        logger.exception("action=asr_bridge_read_failed")
        if not final_text_future.done():
            final_text_future.set_result("")
        try:
            await _ws_send_text(upstream_websocket, session_id, {"type": "error", "content": "asr_unavailable"})
        except Exception:
            pass


async def _open_asr_bridge(upstream_websocket: WebSocket, session_id: str) -> AsrBridge | None:
    voice_sem = _get_session_voice_semaphore(session_id)
    if voice_sem.locked():
        await _ws_send_text(upstream_websocket, session_id, {"type": "error", "content": "voice_at_capacity"})
        return None

    await voice_sem.acquire()
    try:
        downstream_websocket = await websockets.connect(
            ASR_SERVICE_WS_URL, max_size=None, open_timeout=10, close_timeout=5,
        )
    except Exception:
        voice_sem.release()
        await _ws_send_text(upstream_websocket, session_id, {"type": "error", "content": "asr_unavailable"})
        return None

    final_text = asyncio.get_running_loop().create_future()
    reader_task = asyncio.create_task(_read_asr_messages(upstream_websocket, session_id, downstream_websocket, final_text))
    return AsrBridge(websocket=downstream_websocket, reader_task=reader_task, final_text=final_text)


async def _close_asr_bridge(bridge: AsrBridge | None, session_id: str = "") -> None:
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
    if session_id in _session_voice_locks:
        _session_voice_locks[session_id].release()
        del _session_voice_locks[session_id]


@router.websocket("/ws/chat/{session_id}")
async def chat_ws(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=""),
) -> None:
    if not token or not verify_session_token(session_id, token):
        await websocket.accept()
        await _ws_send_json(websocket, session_id, {"type": "error", "content": "unauthorized"})
        await websocket.close(code=4401)
        return

    try:
        await asyncio.wait_for(WS_SEMAPHORE.acquire(), timeout=1.0)
    except asyncio.TimeoutError:
        await websocket.accept()
        await _ws_send_json(websocket, session_id, {"type": "error", "content": "server_at_capacity"})
        await websocket.close()
        return

    await websocket.accept()
    logger.info("session_id=%s connected", session_id)

    asr_bridge: AsrBridge | None = None
    asr_rejected = False

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
                    await _ws_send_text(websocket, session_id, {"type": "error", "content": "internal_error"})
                    continue

                message_type = payload.get("type")

                if message_type == "set_voice":
                    prefs = _set_voice_preferences(session_id, voice=payload.get("voice", DEFAULT_VOICE))
                    await _ws_send_text(
                        websocket,
                        session_id,
                        {
                            "type": "voice_preferences_set",
                            "voice": prefs["voice"],
                            "speed": prefs["speed"],
                            "speech_enabled": prefs["speech_enabled"],
                        },
                    )
                    continue

                if message_type == "set_voice_preferences":
                    prefs = _set_voice_preferences(
                        session_id,
                        voice=payload.get("voice"),
                        speed=payload.get("speed"),
                        speech_enabled=payload.get("speech_enabled"),
                    )
                    await _ws_send_text(
                        websocket,
                        session_id,
                        {
                            "type": "voice_preferences_set",
                            "voice": prefs["voice"],
                            "speed": prefs["speed"],
                            "speech_enabled": prefs["speech_enabled"],
                        },
                    )
                    continue

                if message_type == "replay_assistant_message":
                    replay_text = str(payload.get("content", "")).strip()
                    if not replay_text:
                        await _ws_send_text(websocket, session_id, {"type": "error", "content": "replay_empty"})
                        continue
                    await _replay_assistant_message(websocket, session_id, replay_text)
                    continue

                if message_type == "audio_start":
                    if asr_bridge is None:
                        asr_bridge = await _open_asr_bridge(websocket, session_id)
                        asr_rejected = asr_bridge is None
                    continue

                if message_type == "audio_end":
                    if asr_bridge is None:
                        await _ws_send_text(websocket, session_id, {"type": "done", "content": ""})
                        continue

                    try:
                        await asr_bridge.websocket.send(json.dumps({"type": "audio_end"}, ensure_ascii=False))
                        final_text = await asyncio.wait_for(asr_bridge.final_text, timeout=30)
                    except (asyncio.TimeoutError, Exception) as exc:
                        logger.warning("session_id=%s asr_bridge_error=%s", session_id, type(exc).__name__)
                        final_text = ""

                    await _close_asr_bridge(asr_bridge, session_id)
                    asr_bridge = None
                    asr_rejected = False

                    if final_text.strip():
                        await _run_llm_pipeline(websocket, session_id, final_text, tts_enabled=True)
                    else:
                        await _ws_send_text(websocket, session_id, {"type": "done", "content": ""})
                    continue

                if message_type != "user_message":
                    await _ws_send_text(websocket, session_id, {"type": "error", "content": "internal_error"})
                    continue

                user_message = str(payload.get("content", "")).strip()
                if not user_message:
                    await _ws_send_text(websocket, session_id, {"type": "done", "content": ""})
                    continue
                await _run_llm_pipeline(websocket, session_id, user_message, tts_enabled=True)
                continue

            audio_bytes = data.get("bytes")
            if audio_bytes is None:
                continue

            if asr_bridge is None:
                if not asr_rejected:
                    await _ws_send_text(websocket, session_id, {"type": "error", "content": "audio_not_started"})
                    asr_rejected = True
                continue

            await asr_bridge.websocket.send(audio_bytes)

    except WebSocketDisconnect:
        logger.info("session_id=%s disconnected", session_id)
    except Exception as exc:
        logger.exception("session_id=%s error=%s", session_id, type(exc).__name__)
        try:
            await _ws_send_text(websocket, session_id, {"type": "error", "content": "internal_error"})
        except Exception:
            pass
    finally:
        await _close_asr_bridge(asr_bridge, session_id)
        _voice_state.pop(session_id, None)
        _ws_locks.pop(session_id, None)
        _replay_in_progress.pop(session_id, None)
        WS_SEMAPHORE.release()


async def run_chat_rest(request: Request) -> Any:
    """
    Simulates a chat turn for REST clients (evaluations).
    Captures tokens into a single response string.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid_json"})

    session_id = str(body.get("session_id") or uuid.uuid4())
    clear_tracked_tool_calls(session_id)
    user_message = str(body.get("message") or "").strip()
    
    if not user_message:
        return {"response": "", "session_id": session_id}
    
    # Ensure session exists in conv-manager (idempotent)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{CONV_MANAGER_URL}/internal/create-session",
                json={"session_id": session_id},
            )
    except Exception as exc:
        logger.warning("session_id=%s action=run_chat_rest_session_creation_failed error=%s", session_id, type(exc).__name__)

    # Mock WebSocket to reuse _run_llm_pipeline
    class MockWebSocket:
        def __init__(self):
            self.full_response = ""
            self.last_timings = {}
            self.sources = []

        async def accept(self): pass
        async def close(self, code=1000): pass
        
        async def send_text(self, data_str):
            data = json.loads(data_str)
            if data.get("type") == "token":
                self.full_response += data.get("content", "")
            elif data.get("type") == "done":
                self.last_timings = data.get("timings", {})
                self.sources = data.get("sources", [])
        
        async def send_json(self, data):
            await self.send_text(json.dumps(data))
            
        async def send_bytes(self, data): pass

    mock_ws = MockWebSocket()
    
    # Run the pipeline
    # We pass tts_enabled=False to avoid overhead during evals
    try:
        await _run_llm_pipeline(mock_ws, session_id, user_message, tts_enabled=False)
    except Exception as exc:
        logger.exception("session_id=%s action=run_chat_rest_failed error=%s", session_id, type(exc).__name__)
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": str(exc)})
    
    headers = {
        "X-Retrieval-Time-Ms": str(mock_ws.last_timings.get("tool_exec_ms_0", 0) if "search_docs" in str(mock_ws.last_timings.get("tool_name")) else 0),
        "X-Tool-Time-Ms": str(mock_ws.last_timings.get("tool_exec_ms_0", 0) if "search_docs" not in str(mock_ws.last_timings.get("tool_name")) else 0)
    }
    
    return JSONResponse(
        content={
            "response": mock_ws.full_response,
            "session_id": session_id,
            "timings": mock_ws.last_timings,
            "sources": mock_ws.sources
        },
        headers=headers
    )
