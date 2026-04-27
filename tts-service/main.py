from __future__ import annotations

import asyncio
import io
import logging
import os
from contextlib import asynccontextmanager

import soundfile as sf
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from kokoro_onnx import Kokoro
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tts-service")

MODEL_PATH = os.getenv("KOKORO_MODEL_PATH", "kokoro-v1_0.onnx")
VOICES_PATH = os.getenv("KOKORO_VOICES_PATH", "voices-v1_0.bin")
DEFAULT_VOICE = os.getenv("KOKORO_DEFAULT_VOICE", "af_bella")
DEFAULT_LANGUAGE = "en-us"

_kokoro: Kokoro | None = None
_available_voices: set[str] = set()
_kokoro_semaphore = asyncio.Semaphore(2)


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = DEFAULT_VOICE
    speed: float = 1.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _kokoro, _available_voices
    try:
        loop = asyncio.get_running_loop()
        _kokoro = await loop.run_in_executor(None, Kokoro, MODEL_PATH, VOICES_PATH)
        _available_voices = set(_kokoro.get_voices())
        logger.info("action=model_loaded voice_count=%d", len(_available_voices))
    except Exception:
        logger.exception("action=model_load_failed")
        _kokoro = None
        _available_voices = set()
    yield
    _kokoro = None
    _available_voices = set()


app = FastAPI(title="tts-service", lifespan=lifespan)


@app.get("/health")
def health():
    if _kokoro is None:
        return JSONResponse(status_code=503, content={"error": "model_not_loaded"})
    return {"status": "ok", "model": "kokoro-onnx"}


@app.get("/voices")
def voices() -> dict[str, list[str]]:
    return {"voices": sorted(_available_voices)}


@app.post("/synthesize")
async def synthesize(request: SynthesizeRequest):
    if _kokoro is None:
        return JSONResponse(status_code=503, content={"error": "model_not_loaded"})

    text = request.text.strip()
    if not text:
        return JSONResponse(status_code=422, content={"error": "empty_text"})
    if request.voice not in _available_voices:
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_voice", "allowed": sorted(_available_voices)},
        )
    if request.speed < 0.25 or request.speed > 3.0:
        return JSONResponse(status_code=422, content={"error": "invalid_speed"})

    try:
        logger.info(
            "action=synthesize_start voice=%s text_len=%d",
            request.voice,
            len(text),
        )
        async with _kokoro_semaphore:
            samples, sample_rate = await asyncio.to_thread(
                _kokoro.create,
                text,
                voice=request.voice,
                speed=request.speed,
                lang=DEFAULT_LANGUAGE,
            )
        buffer = io.BytesIO()
        sf.write(buffer, samples, sample_rate, format="WAV")
        return Response(
            content=buffer.getvalue(),
            media_type="audio/wav",
            headers={"X-Sample-Rate": str(sample_rate)},
        )
    except AssertionError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    except Exception:
        logger.exception("action=synthesize_failed")
        return JSONResponse(status_code=500, content={"error": "synthesis_failed"})
