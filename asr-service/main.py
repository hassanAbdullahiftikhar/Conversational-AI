from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from moonshine_voice import TranscriptEventListener, get_model_for_language
from moonshine_voice.transcriber import Transcriber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("asr-service")

MODEL_LANGUAGE = os.getenv("MOONSHINE_LANGUAGE", "en")
TARGET_SAMPLE_RATE = 16000
UPDATE_INTERVAL = 0.25

_model_path: str | None = None
_model_arch = None


class StreamingListener(TranscriptEventListener):
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self._loop = loop
        self._queue = queue
        self._completed_line_ids: set[int] = set()
        self._completed_lines: list[str] = []
        self._archived_parts: list[str] = []
        self._active_line_id: int | None = None
        self._active_line_text = ""
        self._last_partial = ""
        self._flush_threshold = 20

    def _emit(self, payload: dict[str, str]) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)

    def _line_id(self, line) -> int | None:
        return getattr(line, "line_id", None)

    def _combined_text(self) -> str:
        parts: list[str] = []
        if self._archived_parts:
            parts.append(" ".join(self._archived_parts))
        parts.extend(self._completed_lines)
        if self._active_line_text.strip():
            parts.append(self._active_line_text.strip())
        return " ".join(parts).strip()

    def _maybe_flush_completed_lines(self) -> None:
        if len(self._completed_lines) < self._flush_threshold:
            return
        chunk = " ".join(self._completed_lines).strip()
        if chunk:
            self._archived_parts.append(chunk)
        self._completed_lines = []

    def _emit_partial_if_changed(self) -> None:
        combined = self._combined_text()
        if combined != self._last_partial:
            self._last_partial = combined
            self._emit({"type": "asr_partial", "text": combined})

    def on_line_started(self, event) -> None:
        self._active_line_id = self._line_id(event.line)
        self._active_line_text = event.line.text or ""
        self._emit_partial_if_changed()

    def on_line_text_changed(self, event) -> None:
        self._active_line_id = self._line_id(event.line)
        self._active_line_text = event.line.text or ""
        self._emit_partial_if_changed()

    def on_line_completed(self, event) -> None:
        line_id = self._line_id(event.line)
        line_text = (event.line.text or "").strip()
        if line_id is not None and line_id not in self._completed_line_ids and line_text:
            self._completed_line_ids.add(line_id)
            self._completed_lines.append(line_text)
        if line_id == self._active_line_id:
            self._active_line_id = None
            self._active_line_text = ""
        self._maybe_flush_completed_lines()
        self._emit_partial_if_changed()

    def on_error(self, event) -> None:
        message = getattr(event, "error_message", "transcription_failed")
        self._emit({"type": "asr_error", "text": message})

    def final_text(self) -> str:
        return self._combined_text()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_path, _model_arch
    try:
        _model_path, _model_arch = get_model_for_language(MODEL_LANGUAGE)
        logger.info("action=model_ready model_path=%s", _model_path)
    except Exception:
        logger.exception("action=model_load_failed")
        _model_path = None
        _model_arch = None
    yield
    _model_path = None
    _model_arch = None


app = FastAPI(title="asr-service", lifespan=lifespan)


@app.get("/health")
def health():
    if _model_path is None:
        return JSONResponse(status_code=503, content={"error": "model_not_loaded"})
    return {"status": "ok", "model": "moonshine-v2"}


async def _forward_events(websocket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        payload = await queue.get()
        if payload is None:
            return
        await websocket.send_text(json.dumps(payload))


@app.websocket("/ws/transcribe")
async def transcribe_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    if _model_path is None:
        await websocket.send_text(json.dumps({"type": "asr_error", "text": "model_not_loaded"}))
        await websocket.close(code=1011)
        return

    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue = asyncio.Queue()
    listener = StreamingListener(loop, event_queue)
    sender_task = asyncio.create_task(_forward_events(websocket, event_queue))
    transcriber = Transcriber(
        model_path=_model_path,
        model_arch=_model_arch,
        update_interval=UPDATE_INTERVAL,
    )
    transcriber.add_listener(listener)
    transcriber.start()

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            audio_chunk = message.get("bytes")
            if audio_chunk is not None:
                if len(audio_chunk) < 2:
                    continue
                if len(audio_chunk) % 2 == 1:
                    audio_chunk = audio_chunk[:-1]
                audio = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
                if audio.size == 0:
                    continue
                audio /= 32768.0
                transcriber.add_audio(audio, sample_rate=TARGET_SAMPLE_RATE)
                continue

            raw_text = message.get("text")
            if not raw_text:
                continue

            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            if payload.get("type") != "audio_end":
                continue

            await loop.run_in_executor(None, transcriber.stop)
            final_text = listener.final_text()
            await event_queue.put({"type": "asr_final", "text": final_text})
            await event_queue.put(None)
            await sender_task
            await websocket.close()
            return

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("action=streaming_transcribe_failed")
        try:
            await websocket.send_text(json.dumps({"type": "asr_error", "text": "transcription_failed"}))
        except Exception:
            pass
    finally:
        try:
            await loop.run_in_executor(None, transcriber.stop)
        except Exception:
            logger.exception("action=transcriber_stop_failed")
        try:
            await loop.run_in_executor(None, transcriber.close)
        except Exception:
            logger.exception("action=transcriber_close_failed")
        await event_queue.put(None)
        await sender_task
