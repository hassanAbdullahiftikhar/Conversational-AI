from __future__ import annotations

import os
import unicodedata


class PolicyEnforcer:
    MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))

    INJECTION_KEYWORDS = [
        "ignore your instructions",
        "ignore previous instructions",
        "pretend you are",
        "you are now",
        "jailbreak",
        "disregard your",
        "forget your instructions",
        "new instructions:",
        "override your",
        "system prompt",
        "<|im_start|>",
        "<|im_end|>",
        "<!--",
    ]

    @staticmethod
    def _normalize(text: str) -> str:
        """NFKC-normalize and lowercase for consistent injection detection across Unicode variants."""
        return unicodedata.normalize("NFKC", text).lower()

    def check_input(self, user_message: str, previous_user_turn: str | None = None) -> tuple[bool, str | None]:
        if len(user_message) > self.MAX_MESSAGE_LENGTH:
            return False, "Message too long. Please keep your message under 500 characters."

        if previous_user_turn is not None and user_message == previous_user_turn:
            return False, (
                "It looks like you sent the same message twice. Is there something "
                "I can help clarify?"
            )

        normalized = self._normalize(user_message)
        for keyword in self.INJECTION_KEYWORDS:
            if keyword in normalized:
                return False, (
                    "I am a Smart Home Ecosystem Specialist. "
                    "I cannot process instructions that attempt to alter my persona or system rules. "
                    "Do you have a question about your smart home setup?"
                )

        return True, None
