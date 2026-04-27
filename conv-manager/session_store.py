from __future__ import annotations

import os
import threading
import time
from typing import Dict, Optional
import aiosqlite
import json
from pathlib import Path
from asyncio import Lock

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "7200"))  # 2-hour idle TTL
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "1000"))  # hard cap against memory exhaustion

# SQLite persistence for CRM - use /tmp which is always writable in Docker
_CRM_DB = Path("/tmp/crm_profiles.db")
_CRM_LOCK = Lock()


async def _init_crm_db():
    """Initialize CRM SQLite database with WAL mode."""
    async with aiosqlite.connect(_CRM_DB, isolation_level=None) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS crm_profiles (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                profile_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON crm_profiles(user_id)")


class SessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def _evict_expired_locked(self) -> None:
        """Evict sessions idle longer than SESSION_TTL_SECONDS. Must be called with _lock held."""
        if SESSION_TTL_SECONDS <= 0:
            return
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.get("last_accessed", s["created_at"]) > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]

    def create_session(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                return
            self._evict_expired_locked()
            if len(self._sessions) >= MAX_SESSIONS:
                # Evict the least-recently-accessed session to stay within cap.
                oldest = min(self._sessions, key=lambda sid: self._sessions[sid].get("last_accessed", 0))
                del self._sessions[oldest]
            now = time.time()
            self._sessions[session_id] = {
                "session_id": session_id,
                "created_at": now,
                "last_accessed": now,
                "turns": [],
                "metadata": {
                    "memory_summary": "",
                    "memory_summary_hash": "",
                    "last_user_message": "",
                },
            }

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session["last_accessed"] = time.time()
            return {
                "session_id": session["session_id"],
                "created_at": session["created_at"],
                "turns": list(session["turns"]),
                "metadata": dict(session["metadata"]),
            }

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())

    def append_turn(self, session_id: str, role: str, content: str) -> int:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return 0
            session["turns"].append({"role": role, "content": content})
            session["last_accessed"] = time.time()
            if role == "user":
                session["metadata"]["last_user_message"] = content
            return len(session["turns"])

    def get_turns(self, session_id: str) -> list[dict]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            session["last_accessed"] = time.time()
            return list(session["turns"])

    def replace_turns(self, session_id: str, turns: list[dict]) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session["turns"] = list(turns)

    def compact_turns(self, session_id: str, original_count: int, replacement: list[dict]) -> None:
        """Replace the first `original_count` turns with `replacement`, preserving any newer turns added since."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            current_turns = session["turns"]
            new_turns = current_turns[original_count:]
            session["turns"] = list(replacement) + new_turns

    def get_memory_summary(self, session_id: str) -> tuple[str, str]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return "", ""
            metadata = session.get("metadata", {})
            summary = str(metadata.get("memory_summary", ""))
            summary_hash = str(metadata.get("memory_summary_hash", ""))
            return summary, summary_hash

    def set_memory_summary(self, session_id: str, summary: str, summary_hash: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            metadata = session.setdefault("metadata", {})
            metadata["memory_summary"] = summary
            metadata["memory_summary_hash"] = summary_hash

    def clear_turns(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session["turns"] = []
            metadata = session.setdefault("metadata", {})
            metadata["memory_summary"] = ""
            metadata["memory_summary_hash"] = ""
            metadata["last_user_message"] = ""

    def get_crm_profile(self, session_id: str) -> dict:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}
            metadata = session.setdefault("metadata", {})
            profile = metadata.get("crm_profile")
            if isinstance(profile, dict):
                return dict(profile)
            return {}

    def update_crm_profile(self, session_id: str, updates: dict) -> dict:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}

            metadata = session.setdefault("metadata", {})
            existing = metadata.get("crm_profile")
            profile = dict(existing) if isinstance(existing, dict) else {}
            profile.update({k: v for k, v in updates.items() if v is not None})
            metadata["crm_profile"] = profile
            return dict(profile)

    async def get_crm_profile_async(self, session_id: str) -> dict:
        async with _CRM_LOCK:
            async with aiosqlite.connect(str(_CRM_DB), isolation_level=None) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT profile_json FROM crm_profiles WHERE session_id = ?",
                    (session_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return json.loads(row["profile_json"])
                    return {}

    async def update_crm_profile_async(self, session_id: str, updates: dict) -> dict:
        async with _CRM_LOCK:
            async with aiosqlite.connect(str(_CRM_DB), isolation_level=None) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT profile_json FROM crm_profiles WHERE session_id = ?",
                    (session_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    current = json.loads(row["profile_json"]) if row else {}
                current.update({k: v for k, v in updates.items() if v is not None})
                profile_json = json.dumps(current, ensure_ascii=False)
                now = time.time()
                await db.execute(
                    """INSERT INTO crm_profiles (session_id, profile_json, updated_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(session_id) DO UPDATE SET
                       profile_json = excluded.profile_json,
                       updated_at = excluded.updated_at""",
                    (session_id, profile_json, now)
                )
                return dict(current)

    async def get_profile_by_user_id_async(self, user_id: str) -> dict | None:
        async with _CRM_LOCK:
            async with aiosqlite.connect(str(_CRM_DB), isolation_level=None) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT profile_json FROM crm_profiles WHERE user_id = ?",
                    (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return json.loads(row["profile_json"])
                    return None
