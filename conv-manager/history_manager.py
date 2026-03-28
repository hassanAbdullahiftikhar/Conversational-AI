from __future__ import annotations

import asyncio
import hashlib

from memory_summarizer import MemorySummarizer
from session_store import SessionStore


class HistoryManager:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self._compact_locks: dict[str, asyncio.Lock] = {}

    def _get_compact_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._compact_locks:
            self._compact_locks[session_id] = asyncio.Lock()
        return self._compact_locks[session_id]

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        self.store.append_turn(session_id=session_id, role=role, content=content)

    def get_history(self, session_id: str, max_turns: int = 10) -> list[dict]:
        turns = self.store.get_turns(session_id)
        if not turns:
            return []
        return turns[-max_turns:]

    def get_summary(self, session_id: str) -> str:
        summary, _ = self.store.get_memory_summary(session_id)
        return summary

    def get_recent_full_history(self, session_id: str, recent_rounds: int = 5) -> list[dict]:
        if recent_rounds <= 0:
            return []
        turns = self.store.get_turns(session_id)
        return turns[-(recent_rounds * 2):]

    async def compact_memory(
        self,
        session_id: str,
        summarizer: MemorySummarizer,
        max_total_rounds: int = 20,
        recent_full_rounds: int = 5,
        summarized_rounds_limit: int = 15,
    ) -> None:
        lock = self._get_compact_lock(session_id)
        async with lock:
            turns = self.store.get_turns(session_id)
            if not turns:
                self.store.set_memory_summary(session_id, "", "")
                return

            rounds = self._turns_to_rounds(turns)
            rounds = rounds[-max_total_rounds:]

            recent_rounds_list = rounds[-recent_full_rounds:]
            older_rounds = rounds[:-recent_full_rounds]
            older_rounds = older_rounds[-summarized_rounds_limit:]

            summary_input = self._rounds_to_text(older_rounds)
            source_hash = hashlib.sha256(summary_input.encode("utf-8")).hexdigest() if summary_input else ""

            prev_summary, prev_hash = self.store.get_memory_summary(session_id)
            summary = prev_summary

            if not older_rounds:
                summary = ""
                source_hash = ""
            elif source_hash != prev_hash:
                try:
                    summary = await summarizer.summarize(summary_input)
                except Exception:
                    summary = prev_summary

            self.store.compact_turns(session_id, len(turns), self._flatten_rounds(recent_rounds_list))
            self.store.set_memory_summary(session_id, summary, source_hash)

    def _turns_to_rounds(self, turns: list[dict]) -> list[list[dict]]:
        rounds: list[list[dict]] = []
        current: list[dict] = []
        for turn in turns:
            current.append(turn)
            if len(current) == 2:
                rounds.append(current)
                current = []
        # Discard any dangling single-turn tail to preserve user/assistant role alignment.
        return rounds

    def _flatten_rounds(self, rounds: list[list[dict]]) -> list[dict]:
        flat: list[dict] = []
        for round_turns in rounds:
            flat.extend(round_turns)
        return flat

    def _rounds_to_text(self, rounds: list[list[dict]]) -> str:
        lines: list[str] = []
        for idx, round_turns in enumerate(rounds, start=1):
            lines.append(f"Round {idx}:")
            for turn in round_turns:
                role = str(turn.get("role", "user"))
                content = str(turn.get("content", ""))
                lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    def trim_to_token_budget(self, history: list[dict], token_budget: int = 1600) -> list[dict]:
        if token_budget <= 0:
            return []

        def estimate_tokens(turns: list[dict]) -> int:
            total_chars = sum(len(str(t.get("content", ""))) for t in turns)
            # 3 chars/token is conservative for mixed-script text (Urdu, Arabic, Latin).
            return total_chars // 3

        trimmed = list(history)
        while trimmed and estimate_tokens(trimmed) > token_budget:
            trimmed.pop(0)
        return trimmed

    def clear_history(self, session_id: str) -> None:
        self.store.clear_turns(session_id)
        self._compact_locks.pop(session_id, None)
