from __future__ import annotations

import os

import httpx


class MemorySummarizer:
    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_URL", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "gemma-4-E4B-it")
        self.temperature = float(os.getenv("SUMMARY_TEMPERATURE", "0.2"))

    async def summarize(self, rounds_text: str) -> str:
        if not rounds_text.strip():
            return ""

        prompt = (
            "You are a conversation memory compressor for a customer support assistant.\n"
            "Summarize the provided conversation rounds with very high signal and low noise.\n"
            "Rules:\n"
            "1) Keep only durable facts relevant for next turns.\n"
            "2) Preserve user identity details if explicitly provided (name, city), but mask phone numbers as last 4 digits only.\n"
            "3) Preserve unresolved issues, user intent, and key corrections/preferences.\n"
            "4) Do not include filler, style commentary, or repeated refusals.\n"
            "5) Output 6-10 concise bullet points.\n"
            "\n"
            "Conversation rounds to compress:\n"
            f"{rounds_text}\n"
        )

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": self.temperature,
            "max_tokens": 250,
        }

        timeout = httpx.Timeout(connect=10.0, write=30.0, read=90.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            
            choices = data.get("choices", [])
            if not choices:
                return ""
                
            message = choices[0].get("message", {})
            return str(message.get("content", "")).strip()
