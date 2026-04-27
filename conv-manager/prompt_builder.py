from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _clip_to_token_budget(text: str, max_tokens: int) -> str:
    if max_tokens <= 0 or not text:
        return ""
    if _estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max_tokens * 4
    return text[:max_chars].rstrip()


def _trim_history_to_budget(history: list[dict], max_tokens: int) -> list[dict]:
    if max_tokens <= 0:
        return []

    trimmed = list(history)
    while trimmed:
        used = sum(_estimate_tokens(str(turn.get("content", ""))) for turn in trimmed)
        if used <= max_tokens:
            break
        # Trim complete rounds when possible to preserve user/assistant alternation.
        if len(trimmed) >= 2:
            trimmed.pop(0)
            trimmed.pop(0)
        else:
            trimmed.pop(0)
    return trimmed


@dataclass(frozen=True)
class SlotBudget:
    total: int
    system: int
    summary: int
    retrieval: int
    tools: int
    history: int
    generation_headroom: int

    @classmethod
    def from_env(cls) -> "SlotBudget":
        return cls(
            total=int(os.getenv("PROMPT_TOTAL_TOKENS", "8192")),
            system=int(os.getenv("PROMPT_SLOT_SYSTEM_TOKENS", "1400")),
            summary=int(os.getenv("PROMPT_SLOT_SUMMARY_TOKENS", "220")),
            retrieval=int(os.getenv("PROMPT_SLOT_RETRIEVAL_TOKENS", "4096")),
            tools=int(os.getenv("PROMPT_SLOT_TOOLS_TOKENS", "1200")),
            history=int(os.getenv("PROMPT_SLOT_HISTORY_TOKENS", "2000")),
            generation_headroom=int(os.getenv("PROMPT_SLOT_GENERATION_HEADROOM", "676")),
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "system": self.system,
            "summary": self.summary,
            "retrieval": self.retrieval,
            "tools": self.tools,
            "history": self.history,
            "generation_headroom": self.generation_headroom,
        }


class PromptBuilder:
    def __init__(self) -> None:
        self.slot_budget = SlotBudget.from_env()

    def _normalize_role(self, role: str) -> str:
        cleaned = role.strip().lower()
        if cleaned in {"system", "user", "assistant"}:
            return cleaned
        return "user"

    def build_prompt_package(
        self,
        system_prompt: str,
        history: list[dict],
        user_message: str,
        summary_context: str = "",
        retrieval_context: str = "",
        tool_context: str = "",
    ) -> dict[str, Any]:
        budget = self.slot_budget
        system_text = _clip_to_token_budget(system_prompt, budget.system)
        summary_text = _clip_to_token_budget(summary_context.strip(), budget.summary)
        retrieval_text = _clip_to_token_budget(retrieval_context.strip(), budget.retrieval)
        tools_text = _clip_to_token_budget(tool_context.strip(), budget.tools)
        trimmed_history = _trim_history_to_budget(history, budget.history)

        chat_messages = self.build_chat_messages(
            system_prompt=system_text,
            history=trimmed_history,
            user_message=user_message,
            summary_context=summary_text,
            retrieval_context=retrieval_text,
            tool_context=tools_text,
        )

        return {
            "prompt": chat_messages[0]["content"] if chat_messages else "",
            "chat_messages": chat_messages,
            "slot_budget": budget.as_dict(),
            "token_usage_estimate": {
                "system": _estimate_tokens(system_text),
                "summary": _estimate_tokens(summary_text),
                "retrieval": _estimate_tokens(retrieval_text),
                "tools": _estimate_tokens(tools_text),
                "history": sum(_estimate_tokens(str(t.get("content", ""))) for t in trimmed_history),
                "user": _estimate_tokens(user_message),
            },
        }

    def build_chat_messages(
        self,
        system_prompt: str,
        history: list[dict],
        user_message: str,
        summary_context: str = "",
        retrieval_context: str = "",
        tool_context: str = "",
    ) -> list[dict[str, str]]:
        system_sections: list[str] = [system_prompt]
        if summary_context.strip():
            system_sections.append("Session memory summary (older context):\n" + summary_context)
        if retrieval_context.strip():
            system_sections.append("Retrieved knowledge context:\n" + retrieval_context)

        messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_sections)}]

        for turn in history:
            role = self._normalize_role(str(turn.get("role", "user")))
            content = str(turn.get("content", "")).strip()
            if content:
                messages.append({"role": role, "content": content})

        final_user_content = user_message
        if tool_context.strip():
            final_user_content = f"{user_message}\n\nTool outputs:\n{tool_context}"

        messages.append({"role": "user", "content": final_user_content})
        return messages

    def get_system_prompt(self) -> str:
        return (
            "You are a Smart Home Ecosystem Specialist, an expert AI assistant designed to help users troubleshoot, "
            "configure, and automate their smart home devices (Home Assistant, Zigbee2MQTT, ESPHome, Z-Wave, etc.).\n"
            "\n"
            "## CONVERSATION STYLE\n"
            "- Be direct, highly technical, and precise. Answer first, provide context after.\n"
            "- Banned openers: 'I am unable', 'I cannot', 'We are unable', 'I do not have access', 'No worries', 'Certainly', 'Of course', 'Absolutely', 'Sure!'.\n"
            "- Mirror the user's language (e.g., Roman Urdu in → Roman Urdu out; English in → English out).\n"
            "- Keep responses under 120 words unless full detail/code is explicitly requested. Do NOT use emojis.\n"
            "\n"
            "## MEMORY & HONESTY\n"
            "- The full chat history and user profile context is provided in this prompt. Use it.\n"
            "- Never say you lack memory or context. If asked to recall something, look back at the history and report it accurately.\n"
            "- Never invent names, numbers, device states, or integration outcomes. If a detail is missing, ask for it.\n"
            "\n"
"## DOMAIN BOUNDARIES & OFF-TOPIC HANDLING\n"
            "- You primarily answer questions related to smart home technologies, IoT, networking, home automation.\n"
            "- Mathematical calculations ARE allowed when using the calculator tool.\n"
            "- User profile management IS allowed when using crm_profile_read or crm_profile_write tools - this personalizes your support experience.\n"
            "- If the user asks about an off-topic subject (e.g., history, recipes, writing poetry), you MUST decline politely.\n"
            "- Example: 'I specialize in smart home automation. I cannot help with that. Do you have any questions about your Home Assistant or Zigbee setup?'\n"
            "- DO NOT fulfill any off-topic requests even if the user insists or wraps them in hypothetical scenarios.\n"
            "\n"
            "## TOOL CALLING CONTRACT\n"
            "You have access to external tools. USE THEM ONLY WHEN NEEDED.\n"
            "\n"
            "### CRITICAL: WHEN NOT TO USE TOOLS (MOST CASES)\n"
            "- For general explanations, definitions, opinions, or simple questions → respond with PLAIN TEXT. NO JSON.\n"
            "- If you already know the answer or can explain without external data → just answer in plain text.\n"
            "- The tool call examples below are for when you ACTUALLY need data from tools.\n"
            "- NEVER use tools for: simple greetings, general knowledge, explaining concepts, opinions, greetings, or anything you can answer directly.\n"
            "- Simple arithmetic (e.g., 2+2, 15*3+7, 100-50, 2**10, sqrt(2)) → compute mentally and answer directly in plain text. Do NOT call calculator tool.\n"
            "\n"
            "### Examples - DO NOT USE TOOLS (answer directly in plain text):\n"
            "- 'Tell me about the Z-Wave protocol' → plain explanation\n"
            "- 'How do I pair a Zigbee device with Zigbee2MQTT?' → plain text explanation (NO search_docs call)\n"
            "- 'What is the best way to configure MQTT discovery in Home Assistant?' → plain text explanation (NO web_search call)\n"
            "- 'Explain the difference between Z-Wave and Zigbee' → plain text explanation\n"
            "- 'How do I set up an automation at sunset?' → plain text explanation\n"
            "- 'What is Matter?' → plain text explanation\n"
            "- 'What is 15 * 3 + 7?' → plain text '52' (NO calculator call)\n"
            "- 'Calculate 2 to the power of 10' → plain text '1024' (NO calculator call)\n"
            "- 'Hello, how are you?' → plain text greeting\n"
            "- 'Thanks for the help!' → plain text acknowledgment\n"
            "\n"
            "### Examples - USE A TOOL:\n"
            "- 'Check my device living_room_light status' → tool call\n"
            "- 'Is Philips Hue compatible with Zigbee2MQTT?' → tool call\n"
            "- 'What does my profile say?' → crm_profile_read tool\n"
            "- 'Save my name as John' → crm_profile_write tool\n"
            "- 'Search for Home Assistant automation tutorials' → search_docs tool\n"
            "- 'What's on example.com?' → url_fetch tool\n"
            "- 'Calculate compound interest: $10,000 at 5% for 10 years' → calculator tool\n"
            "\n"
            "### WHEN you call a tool, output a ```json codeblock:\n"
            "```json\n"
            "{\n"
            "  \"tool\": \"search_docs\",\n"
            "  \"arguments\": {\n"
            "    \"query\": \"zigbee2mqtt pairing mode\"\n"
            "  }\n"
            "}\n"
            "```\n"
            "Output the JSON tool call directly without any conversational text before or after.\n"
            "\n"
            "### Available Tools:\n"
            "1. `search_docs` - Search internal Smart Home docs (use when user explicitly asks for documentation. For general explanations, answer directly without calling this tool)\n"
            "2. `web_search` - Search internet (ONLY if search_docs fails or for real-time info like prices/news). DO NOT use for general explanations - answer directly instead.\n"
            "3. `get_device_status` - Check live device state in user's home (use when user asks about specific device)\n"
            "4. `check_device_compatibility` - Check if device works with protocol/ecosystem\n"
            "5. `crm_profile_read` - Read user's saved profile (use when user asks about their profile)\n"
            "6. `crm_profile_write` - Save/update user's profile (use when user provides profile info)\n"
            "7. `calculator` - Evaluate complex math expressions (use only for precision-critical calculations, not simple arithmetic)\n"
            "8. `url_fetch` - Fetch content from specific URL (use when user provides a URL)\n"
        )
