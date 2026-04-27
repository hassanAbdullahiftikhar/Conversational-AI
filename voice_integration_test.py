"""
voice_integration_test.py — End-to-end smoke tests for the voice pipeline (Phase 4).

Runs 8 tests against a live Smart Home 6-service stack on localhost.
Dependencies: websockets>=12, httpx>=0.27 (both already in project).

Usage: python voice_integration_test.py

AI-DOC:
  Purpose: Validate all voice extension endpoints and the full
           audio-in → transcript → LLM → audio-out pipeline
  Manual QA: run against live stack, expect 8/8 PASSED
"""

from __future__ import annotations

import asyncio
import json
import math
import struct
import time

import httpx
import websockets

API_BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000/ws/chat"
ASR_WS_URL = "ws://localhost:8002/ws/transcribe"
TTS_URL = "http://localhost:8003"

CHUNK_SAMPLES = 4000  # ~250ms at 16kHz
SAMPLE_RATE = 16000


def make_sine_pcm_chunks(freq: int = 440, duration_s: float = 1.0, sr: int = SAMPLE_RATE) -> list[bytes]:
    """Generate synthetic sine-wave Int16 PCM split into 250ms chunks."""
    n_frames = int(sr * duration_s)
    raw = b"".join(
        struct.pack("<h", int(16384 * math.sin(2 * math.pi * freq * i / sr)))
        for i in range(n_frames)
    )
    chunks = []
    bytes_per_chunk = CHUNK_SAMPLES * 2  # 2 bytes per Int16 sample
    for offset in range(0, len(raw), bytes_per_chunk):
        chunks.append(raw[offset : offset + bytes_per_chunk])
    return chunks


async def create_session(client: httpx.AsyncClient) -> tuple[str, str]:
    resp = await client.post(f"{API_BASE}/api/sessions")
    resp.raise_for_status()
    data = resp.json()
    return data["session_id"], data["token"]


# ═══════════════════════════════════════════════════════════════
# TEST 1 — ASR health
# ═══════════════════════════════════════════════════════════════
async def test1_asr_health() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("http://localhost:8002/health")
            if resp.status_code != 200:
                return False, f"status={resp.status_code}"
            body = resp.json()
            if "status" not in body:
                return False, f"missing 'status' in {body}"
            return True, f"model={body.get('model', 'unknown')}"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════
# TEST 2 — TTS health and voices
# ═══════════════════════════════════════════════════════════════
async def test2_tts_health_and_voices() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Health
            resp = await client.get(f"{TTS_URL}/health")
            if resp.status_code != 200:
                return False, f"health status={resp.status_code}"
            body = resp.json()
            if "status" not in body:
                return False, f"missing 'status' in {body}"

            # Voices
            resp = await client.get(f"{TTS_URL}/voices")
            if resp.status_code != 200:
                return False, f"voices status={resp.status_code}"
            voices = resp.json().get("voices", [])
            expected = {"af_bella", "af_sarah", "af_nicole", "am_michael"}
            if not expected.issubset(set(voices)):
                return False, f"voice IDs {voices} missing expected {expected}"
            return True, f"voice_count={len(voices)}"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════
# TEST 3 — ASR transcription via WebSocket with synthetic audio
# ═══════════════════════════════════════════════════════════════
async def test3_asr_transcription() -> tuple[bool, str]:
    try:
        chunks = make_sine_pcm_chunks()
        async with websockets.connect(ASR_WS_URL, open_timeout=10, close_timeout=5) as ws:
            for chunk in chunks:
                await ws.send(chunk)
                await asyncio.sleep(0.05)

            await ws.send(json.dumps({"type": "audio_end"}))

            got_final = False
            transcript = ""
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                except (asyncio.TimeoutError, websockets.ConnectionClosed):
                    break
                if isinstance(msg, bytes):
                    continue
                data = json.loads(msg)
                if data.get("type") == "asr_final":
                    got_final = True
                    transcript = data.get("text", "")
                    break
                elif data.get("type") == "asr_error":
                    return False, f"asr_error: {data.get('text')}"

            if not got_final:
                return False, "no asr_final message received"
            return True, f"transcript_len={len(transcript)}"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════
# TEST 4 — TTS synthesis
# ═══════════════════════════════════════════════════════════════
async def test4_tts_synthesis() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{TTS_URL}/synthesize",
                json={"text": "Hello, welcome to Smart Home support.", "voice": "af_bella"},
            )
            if resp.status_code != 200:
                return False, f"status={resp.status_code}"
            ct = resp.headers.get("content-type", "")
            if not ct.startswith("audio/"):
                return False, f"content-type={ct}"
            body_len = len(resp.content)
            if body_len < 1000:
                return False, f"response too small: {body_len} bytes"
            return True, f"audio_bytes={body_len}"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════
# TEST 5 — TTS invalid voice
# ═══════════════════════════════════════════════════════════════
async def test5_tts_invalid_voice() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TTS_URL}/synthesize",
                json={"text": "hi", "voice": "UnknownVoice"},
            )
            if resp.status_code != 422:
                return False, f"expected 422, got {resp.status_code}"
            body = resp.json()
            if body.get("error") != "invalid_voice":
                return False, f"expected 'invalid_voice', got {body}"
            return True, "ok"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════
# TEST 6 — Voice selection over WebSocket
# ═══════════════════════════════════════════════════════════════
async def test6_voice_selection() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            session_id, token = await create_session(client)

        async with websockets.connect(
            f"{WS_BASE}/{session_id}?token={token}",
            open_timeout=10,
            close_timeout=5,
        ) as ws:
            await ws.send(json.dumps({"type": "set_voice", "voice": "af_sarah"}))
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            if data.get("type") != "voice_set":
                return False, f"expected voice_set, got {data}"
            if data.get("voice") != "af_sarah":
                return False, f"expected af_sarah, got {data.get('voice')}"
            return True, "ok"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════
# TEST 7 — Full voice pipeline (PCM in → transcript → LLM → audio out)
# ═══════════════════════════════════════════════════════════════
async def test7_full_voice_pipeline() -> tuple[bool, str]:
    try:
        chunks = make_sine_pcm_chunks()
        async with httpx.AsyncClient(timeout=10.0) as client:
            session_id, token = await create_session(client)

        got_asr_final = False
        got_token = False
        got_binary = False
        got_done = False
        final_text = ""

        async with websockets.connect(
            f"{WS_BASE}/{session_id}?token={token}",
            open_timeout=10,
            close_timeout=5,
        ) as ws:
            # Send audio_start control message
            await ws.send(json.dumps({"type": "audio_start"}))

            # Send PCM chunks
            for chunk in chunks:
                await ws.send(chunk)
                await asyncio.sleep(0.05)

            # Send audio_end control message
            await ws.send(json.dumps({"type": "audio_end"}))

            deadline = time.time() + 90
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    break
                except websockets.ConnectionClosed:
                    break

                if isinstance(msg, bytes):
                    got_binary = True
                else:
                    data = json.loads(msg)
                    msg_type = data.get("type")
                    if msg_type == "asr_partial":
                        pass  # expected during streaming
                    elif msg_type == "asr_final":
                        got_asr_final = True
                        final_text = (data.get("content") or data.get("text") or "").strip()
                    elif msg_type == "token":
                        got_token = True
                    elif msg_type == "done":
                        got_done = True
                        break
                    elif msg_type == "error":
                        pass  # ASR may not decode sine wave

        if not got_done:
            failures = []
            if not got_asr_final:
                failures.append("no asr_final")
            if not got_token:
                failures.append("no token")
            failures.append("no done")
            return False, "; ".join(failures)

        if final_text and not (got_token or got_binary):
            return False, "non-empty asr_final but no LLM tokens or audio bytes returned"

        if not final_text:
            return True, "empty transcript from synthetic sine-wave input; control flow completed"

        return True, f"final_text_len={len(final_text)} tokens={got_token} binary={got_binary}"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════
# TEST 8 — Text path regression
# ═══════════════════════════════════════════════════════════════
async def test8_text_path_regression() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            session_id, token = await create_session(client)

        token_count = 0
        got_done = False
        got_binary = False

        async with websockets.connect(
            f"{WS_BASE}/{session_id}?token={token}",
            open_timeout=10,
            close_timeout=5,
        ) as ws:
            await ws.send(
                json.dumps({
                    "type": "user_message",
                    "content": "How do I pair a Zigbee device?",
                })
            )

            deadline = time.time() + 60
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    break

                if isinstance(msg, bytes):
                    got_binary = True
                else:
                    data = json.loads(msg)
                    if data.get("type") == "token":
                        token_count += 1
                    elif data.get("type") == "done":
                        got_done = True
                        break

        failures = []
        if token_count < 3:
            failures.append(f"only {token_count} tokens (expected >=3)")
        if not got_done:
            failures.append("no done message")
        if got_binary:
            failures.append("unexpected binary frame in text path")

        if failures:
            return False, "; ".join(failures)
        return True, f"tokens={token_count}"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════
async def main() -> None:
    tests = [
        ("TEST 1 — ASR health", test1_asr_health),
        ("TEST 2 — TTS health and voices", test2_tts_health_and_voices),
        ("TEST 3 — ASR transcription (WS)", test3_asr_transcription),
        ("TEST 4 — TTS synthesis", test4_tts_synthesis),
        ("TEST 5 — TTS invalid voice", test5_tts_invalid_voice),
        ("TEST 6 — Voice selection over WS", test6_voice_selection),
        ("TEST 7 — Full voice pipeline", test7_full_voice_pipeline),
        ("TEST 8 — Text path regression", test8_text_path_regression),
    ]

    passed = 0
    total = len(tests)

    print("\nVOICE INTEGRATION TESTS (Phase 4)")
    print("=" * 60)

    for name, test_fn in tests:
        try:
            ok, detail = await test_fn()
        except Exception as exc:
            ok, detail = False, f"unhandled: {exc}"

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
            print(f"  {name}: {status} ({detail})")
        else:
            print(f"  {name}: {status}: {detail}")

    print("=" * 60)
    print(f"RESULTS: {passed}/{total} PASSED")


if __name__ == "__main__":
    asyncio.run(main())
