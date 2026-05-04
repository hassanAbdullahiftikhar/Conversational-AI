from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger("api-gateway.eval_state")
_last_tool_calls: dict[str, list[dict[str, Any]]] = {}

def track_tool_calls(session_id: str, tool_calls: list[dict[str, Any]]):
    if not tool_calls:
        return
    logger.info("action=track_tool_calls session_id=%s count=%d", session_id, len(tool_calls))
    # Append if already exists for this session (for multi-turn/chained tools)
    if session_id in _last_tool_calls:
        _last_tool_calls[session_id].extend(tool_calls)
    else:
        _last_tool_calls[session_id] = tool_calls

def get_tracked_tool_calls(session_id: str) -> list[dict[str, Any]]:
    calls = _last_tool_calls.get(session_id, [])
    logger.info("action=get_tracked_tool_calls session_id=%s found=%d", session_id, len(calls))
    return calls

def clear_tracked_tool_calls(session_id: str):
    if session_id in _last_tool_calls:
        del _last_tool_calls[session_id]
