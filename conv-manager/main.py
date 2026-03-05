from __future__ import annotations

import logging

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from history_manager import HistoryManager
from memory_summarizer import MemorySummarizer
from policy_enforcer import PolicyEnforcer
from prompt_builder import PromptBuilder
from session_store import SessionStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("conv-manager")

app = FastAPI(title="conversation-manager")

_store = SessionStore()
_history = HistoryManager(_store)
_summarizer = MemorySummarizer()
_prompt_builder = PromptBuilder()
_policy_enforcer = PolicyEnforcer()


class BuildPromptRequest(BaseModel):
    session_id: str
    user_message: str


class UpdateHistoryRequest(BaseModel):
    session_id: str
    role: str
    content: str


class SessionRequest(BaseModel):
    session_id: str


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
        trimmed = _history.trim_to_token_budget(history)
        summary = _history.get_summary(payload.session_id)
        prompt = _prompt_builder.build_prompt(
            system_prompt=_prompt_builder.get_system_prompt(),
            history=trimmed,
            summary_context=summary,
            user_message=payload.user_message,
        )
        return {"prompt": prompt, "blocked": False, "block_reason": None}
    except Exception as exc:
        logger.exception("action=build_prompt_failed session_id=%s error=%s", payload.session_id, type(exc).__name__)
        raise


@app.post("/internal/update-history")
async def update_history(payload: UpdateHistoryRequest) -> dict:
    try:
        logger.info("action=update_history session_id=%s", payload.session_id)
        _history.add_turn(payload.session_id, payload.role, payload.content)

        if payload.role == "assistant":
            await _history.compact_memory(payload.session_id, _summarizer)

        turn_count = len(_store.get_turns(payload.session_id))
        return {"success": True, "turn_count": turn_count}
    except Exception as exc:
        logger.exception("action=update_history_failed session_id=%s error=%s", payload.session_id, type(exc).__name__)
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


@app.delete("/internal/delete-session/{session_id}")
def delete_session(session_id: str) -> dict:
    try:
        logger.info("action=delete_session session_id=%s", session_id)
        _store.delete_session(session_id)
        return {"success": True}
    except Exception as exc:
        logger.exception("action=delete_session_failed session_id=%s error=%s", session_id, type(exc).__name__)
        raise


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "active_sessions": len(_store.list_sessions())}
