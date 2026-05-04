from __future__ import annotations

import asyncio
import logging
import re

from typing import Any
from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel, Field

from history_manager import HistoryManager
from memory_summarizer import MemorySummarizer
from policy_enforcer import PolicyEnforcer
from prompt_builder import PromptBuilder
from session_store import SessionStore, _init_crm_db
from tool_router import ToolRouter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("conv-manager")

app = FastAPI(title="conversation-manager")

_store = SessionStore()
_history = HistoryManager(_store)
_summarizer = MemorySummarizer()
_prompt_builder = PromptBuilder()
_policy_enforcer = PolicyEnforcer()
_tool_router = ToolRouter(_store)

_HIDDEN_REASONING_BLOCK_RE = re.compile(
    r"<\|think\|>.*?<\|/think\|>|<think>.*?</think>",
    re.IGNORECASE | re.DOTALL,
)


def _sanitize_assistant_history_content(content: str) -> str:
    """Remove hidden reasoning tags before persisting assistant output in session history."""
    cleaned = _HIDDEN_REASONING_BLOCK_RE.sub("", content)
    return cleaned.strip()


async def _safe_compact(session_id: str) -> None:
    """Run memory compaction in the background; log but swallow errors."""
    try:
        await _history.compact_memory(session_id, _summarizer)
    except Exception:
        logger.exception("action=compact_memory_failed session_id=%s", session_id)


class BuildPromptRequest(BaseModel):
    session_id: str
    user_message: str
    retrieval_context: str = ""
    tool_context: str = ""


class UpdateHistoryRequest(BaseModel):
    session_id: str
    role: str
    content: str


class SessionRequest(BaseModel):
    session_id: str


class ToolExecuteRequest(BaseModel):
    session_id: str
    tool: str
    arguments: dict = Field(default_factory=dict)
    call_id: str | None = None


def get_store() -> SessionStore:
    return _store


@app.post("/internal/build-prompt")
async def build_prompt(payload: BuildPromptRequest, store: SessionStore = Depends(get_store)) -> dict:
    try:
        logger.info("action=build_prompt session_id=%s", payload.session_id)
        session = store.get_session(payload.session_id)
        if session is None:
            return {"prompt": None, "blocked": True, "block_reason": "session_not_found"}

        # Use persisted last_user_message — survives compaction that wipes old turns.
        previous_user_turn = session.get("metadata", {}).get("last_user_message") or None
        allowed, reason = _policy_enforcer.check_input(payload.user_message, previous_user_turn)
        if not allowed:
            return {"prompt": None, "blocked": True, "block_reason": reason}

        history = _history.get_recent_full_history(payload.session_id, recent_rounds=5)
        summary = _history.get_summary(payload.session_id)

        prompt_package = _prompt_builder.build_prompt_package(
            system_prompt=_prompt_builder.get_system_prompt(),
            history=history,
            summary_context=summary,
            user_message=payload.user_message,
            retrieval_context=payload.retrieval_context,
            tool_context=payload.tool_context,
        )
        return {
            "prompt": prompt_package["prompt"],
            "chat_messages": prompt_package["chat_messages"],
            "slot_budget": prompt_package["slot_budget"],
            "token_usage_estimate": prompt_package["token_usage_estimate"],
            "blocked": False,
            "block_reason": None,
        }
    except Exception as exc:
        logger.exception("action=build_prompt_failed session_id=%s error=%s", payload.session_id, type(exc).__name__)
        raise


@app.post("/internal/update-history")
async def update_history(payload: UpdateHistoryRequest) -> dict:
    try:
        logger.info("action=update_history session_id=%s", payload.session_id)
        content = payload.content
        if payload.role == "assistant":
            content = _sanitize_assistant_history_content(content)

        _history.add_turn(payload.session_id, payload.role, content)

        if payload.role == "assistant":
            asyncio.create_task(_safe_compact(payload.session_id))

        turn_count = len(_store.get_turns(payload.session_id))
        return {"success": True, "turn_count": turn_count}
    except Exception as exc:
        logger.exception("action=update_history_failed session_id=%s error=%s", payload.session_id, type(exc).__name__)
        raise


@app.post("/internal/tool-router/execute")
async def execute_tool(payload: ToolExecuteRequest) -> dict:
    try:
        logger.info("action=tool_execute session_id=%s tool=%s", payload.session_id, payload.tool)
        return await _tool_router.execute(
            session_id=payload.session_id,
            tool=payload.tool,
            arguments=payload.arguments,
            call_id=payload.call_id,
        )
    except Exception as exc:
        logger.exception(
            "action=tool_execute_failed session_id=%s tool=%s error=%s",
            payload.session_id,
            payload.tool,
            type(exc).__name__,
        )
        raise


@app.post("/internal/reset-session")
def reset_session(payload: SessionRequest) -> dict:
    try:
        logger.info("action=reset_session session_id=%s", payload.session_id)
        _history.clear_history(payload.session_id)
        return {"success": True}
    except Exception as exc:
        logger.exception("action=reset_session_failed session_id=%s error=%s", payload.session_id, type(exc).__name__)
        raise


@app.post("/internal/create-session")
def create_session(payload: SessionRequest) -> dict:
    try:
        logger.info("action=create_session session_id=%s", payload.session_id)
        _store.create_session(payload.session_id)
        return {"success": True}
    except Exception as exc:
        logger.exception("action=create_session_failed session_id=%s error=%s", payload.session_id, type(exc).__name__)
        raise


class CrmWriteRequest(BaseModel):
    key: str
    value: Any


@app.get("/internal/crm/{user_id}/{key}")
async def crm_read(user_id: str, key: str, store: SessionStore = Depends(get_store)) -> dict:
    profile = await store.get_crm_profile_by_user(user_id)
    if key not in profile:
        from fastapi import Response
        return Response(status_code=404)
    return {"value": profile[key]}


@app.post("/internal/crm/{user_id}")
async def crm_write(user_id: str, payload: CrmWriteRequest, store: SessionStore = Depends(get_store)) -> dict:
    profile = await store.update_crm_profile_by_user(user_id, payload.key, payload.value)
    return {"success": True, "profile": profile}


@app.delete("/internal/crm/{user_id}/{key}")
async def crm_delete(user_id: str, key: str, store: SessionStore = Depends(get_store)) -> dict:
    await store.delete_crm_key_by_user(user_id, key)
    return {"success": True}


@app.delete("/internal/delete-session/{session_id}")
def delete_session(session_id: str) -> dict:
    try:
        logger.info("action=delete_session session_id=%s", session_id)
        _store.delete_session(session_id)
        return {"success": True}
    except Exception as exc:
        logger.exception("action=delete_session_failed session_id=%s error=%s", session_id, type(exc).__name__)
        raise


@app.on_event("startup")
async def on_startup() -> None:
    await _init_crm_db()
    asyncio.create_task(_start_ttl_cleanup_task())


async def _start_ttl_cleanup_task() -> None:
    while True:
        await asyncio.sleep(3600)  # Every hour
        _store._evict_expired_locked()
        logger.info("action=ttl_cleanup_ran")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "active_sessions": len(_store.list_sessions())}
