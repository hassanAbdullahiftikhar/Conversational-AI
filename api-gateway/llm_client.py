from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator

import httpx


logger = logging.getLogger("api-gateway.llm_client")


_llm_http_client: httpx.AsyncClient | None = None


async def get_llm_http_client() -> httpx.AsyncClient:
    global _llm_http_client
    if _llm_http_client is None or _llm_http_client.is_closed:
        _llm_http_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0))
    return _llm_http_client


class LlmConnectionError(Exception):
    pass


class LlmClient:
    def __init__(self, base_url: str | None = None, _shared_client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url or os.getenv("LLM_URL", "http://localhost:11434")
        self.base_url = self.base_url.rstrip("/")
        
        self.model = os.getenv("LLM_MODEL", "gemma-4-E4B-it")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "1.0"))
        self.top_p = float(os.getenv("LLM_TOP_P", "0.95"))
        self.top_k = int(os.getenv("LLM_TOP_K", "64"))

        self.last_stream_metrics: dict[str, Any] = {}
        self.last_stream_mode: str = "chat"
        self._client = _shared_client if _shared_client else httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0))

    async def stream(
        self,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        if not messages:
            messages = [{"role": "user", "content": prompt}]
            
        self.last_stream_metrics = {}
        self.last_stream_mode = "chat"

        try:
            payload: dict[str, Any] = {
                "model": model or self.model,
                "messages": messages,
                "stream": True,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
            }

            async with self._client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()

                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line or not line.startswith("data:"):
                        continue

                    event_data = line[len("data:"):].strip()
                    if event_data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(event_data)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(chunk, dict):
                        usage = chunk.get("usage")
                        if isinstance(usage, dict):
                            self.last_stream_metrics = {
                                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                                "completion_tokens": int(usage.get("completion_tokens") or 0),
                                "total_tokens": int(usage.get("total_tokens") or 0),
                            }

                        choices = chunk.get("choices")
                        if isinstance(choices, list) and choices:
                            first_choice = choices[0]
                            if isinstance(first_choice, dict):
                                delta = first_choice.get("delta")
                                if isinstance(delta, dict):
                                    content = delta.get("content")
                                    if content:
                                        yield str(content)
                        
        except Exception as exc:
            logger.exception("action=llm_stream_failed base_url=%s model=%s error=%s", self.base_url, model or self.model, type(exc).__name__)
            raise LlmConnectionError(f"Model connection failed: {str(exc)}") from exc

    async def health_check(self) -> bool:
        url = f"{self.base_url}/health"
        try:
            response = await self._client.get(url)
            return response.status_code == 200
        except httpx.HTTPError:
            return False
