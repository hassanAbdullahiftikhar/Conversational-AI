from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from llm_client import OllamaClient, OllamaConnectionError, OllamaTimeoutError
from session_router import verify_session_token

logger = logging.getLogger("api-gateway.websocket")
router = APIRouter()
CONV_MANAGER_URL = os.getenv("CONV_MANAGER_URL", "http://conv-manager:8001")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
WS_SEMAPHORE = asyncio.Semaphore(10)

# Shared client for conv-manager calls — connection pool reused across requests.
_CM_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_CM_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
_cm_client: httpx.AsyncClient | None = None


def get_cm_client() -> httpx.AsyncClient:
    global _cm_client
    if _cm_client is None or _cm_client.is_closed:
        _cm_client = httpx.AsyncClient(timeout=_CM_TIMEOUT, limits=_CM_LIMITS)
    return _cm_client


@router.websocket("/ws/chat/{session_id}")
async def chat_ws(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=""),
) -> None:
    # Validate HMAC token to prevent session hijacking (1A-02).
    if not token or not verify_session_token(session_id, token):
        await websocket.accept()
        await websocket.send_json({"type": "error", "content": "unauthorized"})
        await websocket.close(code=4401)
        return

    # asyncio is single-threaded: locked() check + acquire() has no yield between
    # them so the check-then-acquire is atomic — no TOCTOU race.
    if WS_SEMAPHORE.locked():
        await websocket.accept()
        await websocket.send_json({"type": "error", "content": "server_at_capacity"})
        await websocket.close()
        return

    await WS_SEMAPHORE.acquire()
    await websocket.accept()
    logger.info("session_id=%s connected", session_id)

    llm = OllamaClient(base_url=OLLAMA_URL)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "internal_error"})
                continue

            if payload.get("type") != "user_message":
                await websocket.send_json({"type": "error", "content": "internal_error"})
                continue

            user_message = str(payload.get("content", ""))

            # build-prompt can trigger memory summarization (~30-90 s on CPU).
            client = get_cm_client()
            build_resp = await client.post(
                f"{CONV_MANAGER_URL}/internal/build-prompt",
                json={"session_id": session_id, "user_message": user_message},
            )
            build_resp.raise_for_status()
            build_data = build_resp.json()

            if build_data.get("blocked"):
                await websocket.send_json({"type": "error", "content": build_data.get("block_reason")})
                continue

            prompt = build_data.get("prompt")
            assistant_response = ""
            token_count = 0

            try:
                async for token in llm.generate(prompt=prompt):
                    token_count += 1
                    assistant_response += token
                    await websocket.send_json({"type": "token", "content": token})
            except (OllamaConnectionError, OllamaTimeoutError):
                await websocket.send_json({"type": "error", "content": "internal_error"})
                continue

            if token_count == 0:
                assistant_response = (
                    "I can help with orders, shipping, returns, warranty, and account FAQs. "
                    "Please share your order ID if this is an order-specific request."
                )
                await websocket.send_json({"type": "token", "content": assistant_response})

            # Assistant turn update re-triggers memory compaction — use the same extended timeout.
            client = get_cm_client()
            await client.post(
                f"{CONV_MANAGER_URL}/internal/update-history",
                json={"session_id": session_id, "role": "user", "content": user_message},
            )
            await client.post(
                f"{CONV_MANAGER_URL}/internal/update-history",
                json={
                    "session_id": session_id,
                    "role": "assistant",
                    "content": assistant_response,
                },
            )

            await websocket.send_json({"type": "done", "content": ""})
    except WebSocketDisconnect:
        logger.info("session_id=%s disconnected", session_id)
    except Exception as exc:
        logger.exception("session_id=%s error=%s", session_id, type(exc).__name__)
        try:
            await websocket.send_json({"type": "error", "content": "internal_error"})
        except Exception:
            pass
    finally:
        WS_SEMAPHORE.release()
