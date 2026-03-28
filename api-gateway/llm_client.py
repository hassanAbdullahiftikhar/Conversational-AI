from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator

import httpx


_generate_timeout = httpx.Timeout(connect=10.0, write=30.0, read=None, pool=30.0)
_generate_client: httpx.AsyncClient | None = None


def _get_generate_client() -> httpx.AsyncClient:
    global _generate_client
    if _generate_client is None or _generate_client.is_closed:
        _generate_client = httpx.AsyncClient(timeout=_generate_timeout)
    return _generate_client


class OllamaTimeoutError(Exception):
    pass


class OllamaConnectionError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://ollama:11434") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen3.5:2b-q4_K_M")
        self.num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "192"))
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
        self.temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.65"))
        self.top_p = float(os.getenv("OLLAMA_TOP_P", "0.9"))
        self.top_k = int(os.getenv("OLLAMA_TOP_K", "40"))
        self.repeat_penalty = float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.08"))
        self.num_gpu = int(os.getenv("OLLAMA_NUM_GPU", "-1"))
        self.keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
        self.think = os.getenv("OLLAMA_THINK", "false").lower() in {"1", "true", "yes"}

        num_thread = os.getenv("OLLAMA_NUM_THREAD")
        self.num_thread = int(num_thread) if num_thread else None

    def _build_payload(self, prompt: str, model: str | None) -> dict:
        options: dict[str, int | float] = {
            "num_predict": self.num_predict,
            "num_ctx": self.num_ctx,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "num_gpu": self.num_gpu,
        }
        if self.num_thread is not None:
            options["num_thread"] = self.num_thread

        return {
            "model": model or self.model,
            "prompt": prompt,
            "stream": True,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": options,
        }

    async def generate(self, prompt: str, model: str | None = None) -> AsyncIterator[str]:
        url = f"{self.base_url}/api/generate"
        payload = self._build_payload(prompt=prompt, model=model)

        try:
            client = _get_generate_client()
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                has_data = False
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    has_data = True
                    data = json.loads(line)
                    token = str(data.get("response", ""))
                    if token:
                        yield token
                if not has_data:
                    raise OllamaTimeoutError("No response from model within timeout.")
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError("Model request timed out.") from exc
        except httpx.ConnectError as exc:
            raise OllamaConnectionError("Unable to connect to model runtime.") from exc
        except httpx.HTTPError as exc:
            raise OllamaConnectionError("Model runtime returned an invalid response.") from exc
        except asyncio.TimeoutError as exc:
            raise OllamaTimeoutError("Model request timed out.") from exc

    async def health_check(self) -> bool:
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(url)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def warmup(self) -> bool:
        """Preload model weights to reduce first-user-message latency."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": "Reply with the single word: ready",
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": 8,
                "num_ctx": self.num_ctx,
                "temperature": 0.0,
                "num_gpu": self.num_gpu,
            },
        }
        try:
            timeout = httpx.Timeout(connect=10.0, write=30.0, read=180.0, pool=30.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
