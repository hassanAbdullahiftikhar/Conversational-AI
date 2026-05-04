from __future__ import annotations

import os
import httpx
import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger("api-gateway.eval")
print("DEBUG: eval_router module initialized")

CONV_MANAGER_URL = os.getenv("CONV_MANAGER_URL", "http://localhost:8001")
RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://localhost:8004")
# Note: In some setups, tools might be handled by conv-manager or a dedicated service.
# Based on the plan, we proxy them through the gateway.

from eval_state import get_tracked_tool_calls

@router.get("/debug/last_tool_calls/{session_id}")
async def get_last_tool_calls(session_id: str):
    calls = get_tracked_tool_calls(session_id)
    return {"session_id": session_id, "tool_calls": calls}

# ── CRM Proxies ─────────────────────────────────────────────────────────────

@router.get("/crm/{user_id}/{key}")
async def crm_read(user_id: str, key: str):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{CONV_MANAGER_URL}/internal/crm/{user_id}/{key}")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Key not found")
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception as e:
        logger.error(f"CRM Read failed: {e}")
        raise HTTPException(status_code=502, detail="Upstream CRM error")

@router.post("/crm/{user_id}")
async def crm_write(user_id: str, request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{CONV_MANAGER_URL}/internal/crm/{user_id}", json=body)
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CRM Write failed: {e}")
        raise HTTPException(status_code=502, detail="Upstream CRM error")

@router.delete("/crm/{user_id}/{key}")
async def crm_delete(user_id: str, key: str):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(f"{CONV_MANAGER_URL}/internal/crm/{user_id}/{key}")
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CRM Delete failed: {e}")
        raise HTTPException(status_code=502, detail="Upstream CRM error")

# ── RAG Proxies ─────────────────────────────────────────────────────────────

@router.post("/rag/retrieve")
async def rag_retrieve(request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Route to conv-manager's search_docs tool
            resp = await client.post(
                f"{CONV_MANAGER_URL}/internal/tool-router/execute",
                json={
                    "tool": "search_docs",
                    "arguments": body,
                    "session_id": "eval-rag-retrieve"
                }
            )
            resp.raise_for_status()
            raw_data = resp.json()
            # Use candidates (raw hits) instead of snippets (parent context) 
            # so the test can verify specific chunk_ids for Recall@K
            return {
                "chunks": raw_data.get("result", {}).get("candidates", []),
                "retrieval_ms": raw_data.get("duration_ms", 0)
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RAG Retrieval failed: {e}")
        raise HTTPException(status_code=502, detail="Upstream RAG error")

# ── Tool Proxies ────────────────────────────────────────────────────────────

@router.post("/tools/{tool_name}")
async def invoke_tool(tool_name: str, request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Re-using the tool execution logic from the gateway's internal router
            resp = await client.post(
                f"{CONV_MANAGER_URL}/internal/tool-router/execute",
                json={
                    "tool": tool_name,
                    "arguments": body,
                    "session_id": "eval-direct-invoke"
                }
            )
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tool invocation failed: {e}")
        raise HTTPException(status_code=502, detail="Upstream Tool error")
