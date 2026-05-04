from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter()
CONV_MANAGER_URL = os.getenv("CONV_MANAGER_URL", "http://localhost:8001")
# Secret used to sign session tokens. Override in production via env var.
_logger = logging.getLogger("api-gateway.session")
_RAW_SECRET = os.getenv("SESSION_SECRET", "change-me-in-production")
if _RAW_SECRET == "change-me-in-production":
    _logger.warning("SESSION_SECRET is using the default value — override via env var in production")
_SECRET = _RAW_SECRET.encode()


def _make_token(session_id: str) -> str:
    return hmac.new(_SECRET, session_id.encode(), hashlib.sha256).hexdigest()


def verify_session_token(session_id: str, token: str) -> bool:
    expected = _make_token(session_id)
    return hmac.compare_digest(expected, token)


def _upstream_error() -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": "upstream_error", "detail": "downstream request failed"},
    )


@router.post("/api/sessions")
async def create_session() -> dict:
    session_id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.post(
                f"{CONV_MANAGER_URL}/internal/create-session",
                json={"session_id": session_id},
            )
            response.raise_for_status()
            token = _make_token(session_id)
            return {"session_id": session_id, "token": token}
    except Exception:
        return _upstream_error()


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, token: str = Query(default="")) -> dict:
    if not token or not verify_session_token(session_id, token):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.delete(
                f"{CONV_MANAGER_URL}/internal/delete-session/{session_id}"
            )
            response.raise_for_status()
            body = response.json()
        return {"success": bool(body.get("success", False))}
    except Exception as exc:
        import logging
        logging.getLogger("api-gateway.session").warning(
            "delete_session upstream failure session_id=%s error=%s", session_id, type(exc).__name__
        )
        return _upstream_error()


@router.post("/api/sessions/{session_id}/reset")
async def reset_session(session_id: str, token: str = Query(default="")) -> dict:
    if not token or not verify_session_token(session_id, token):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.post(
                f"{CONV_MANAGER_URL}/internal/reset-session",
                json={"session_id": session_id},
            )
            response.raise_for_status()
            body = response.json()
        return {"success": bool(body.get("success", False))}
    except Exception:
        return _upstream_error()
