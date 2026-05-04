import json
import time
import asyncio
import httpx
import websockets
import os
from typing import Any, Optional

class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.ws_base_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        self.http_client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)

    async def close(self):
        await self.http_client.aclose()

    # ── Chat ────────────────────────────────────────────────────────────────

    async def chat(
        self,
        session_id: str,
        message: str,
        history: list[dict] | None = None,
        user_id: str | None = None,
    ) -> dict:
        start_time = time.perf_counter()
        payload = {
            "session_id": session_id,
            "message": message,
            "history": history or [],
            "user_id": user_id
        }
        
        try:
            response = await self.http_client.post("/chat", json=payload)
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if response.status_code >= 400:
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "detail": response.text,
                    "latency_ms": latency_ms
                }
            
            data = response.json()
            result = {
                "response": data.get("response", ""),
                "sources": data.get("sources", []),
                "latency_ms": latency_ms,
                "retrieval_ms": float(response.headers.get("X-Retrieval-Time-Ms", 0.0)),
                "tool_ms": float(response.headers.get("X-Tool-Time-Ms", 0.0)),
                "tool_calls": []
            }

            # If EVAL_MODE is detected, fetch last tool calls
            if os.getenv("EVAL_MODE") == "true":
                tool_calls_data = await self.get_last_tool_calls(session_id)
                if not tool_calls_data.get("error"):
                    result["tool_calls"] = tool_calls_data.get("tool_calls", [])

            return result

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return {
                "error": True,
                "status_code": 500,
                "detail": str(e),
                "latency_ms": latency_ms
            }

    async def chat_ws(
        self,
        session_id: str,
        messages: list[dict],
        user_id: str | None = None,
    ) -> dict:
        start_time = time.perf_counter()
        ws_url = f"{self.ws_base_url}/ws/{session_id}"
        
        full_response = ""
        ttft_ms = 0.0
        itl_ms_list = []
        last_token_time = 0.0
        metadata = {}
        total_tokens = 0

        try:
            async with websockets.connect(ws_url) as ws:
                payload = {"messages": messages, "user_id": user_id}
                await ws.send(json.dumps(payload))
                
                async for message in ws:
                    now = time.perf_counter()
                    data = json.loads(message)
                    
                    if data.get("type") == "token":
                        token = data.get("text", "")
                        if not full_response and token.strip():
                            ttft_ms = (now - start_time) * 1000
                        
                        if full_response:
                            itl_ms_list.append((now - last_token_time) * 1000)
                        
                        full_response += token
                        last_token_time = now
                        total_tokens += 1
                        
                    elif data.get("type") == "metadata":
                        metadata = data
                        break
                    elif data.get("type") == "done":
                        # Some implementations might send 'done' instead of 'metadata'
                        metadata = data.get("metadata", {})
                        break

            e2e_ms = (time.perf_counter() - start_time) * 1000
            
            result = {
                "full_response": full_response,
                "ttft_ms": ttft_ms,
                "itl_ms": sum(itl_ms_list) / len(itl_ms_list) if itl_ms_list else 0.0,
                "itl_ms_list": itl_ms_list,
                "e2e_ms": e2e_ms,
                "retrieval_ms": float(metadata.get("retrieval_ms", 0.0)),
                "tool_ms": float(metadata.get("tool_ms", 0.0)),
                "total_tokens": total_tokens,
                "tool_calls": []
            }

            if os.getenv("EVAL_MODE") == "true":
                tool_calls_data = await self.get_last_tool_calls(session_id)
                if not tool_calls_data.get("error"):
                    result["tool_calls"] = tool_calls_data.get("tool_calls", [])

            return result

        except Exception as e:
            return {
                "error": True,
                "status_code": 500,
                "detail": str(e),
                "latency_ms": (time.perf_counter() - start_time) * 1000
            }

    async def measure_ttft(self, session_id: str, message: str) -> float:
        res = await self.chat_ws(session_id, [{"role": "user", "content": message}])
        return res.get("ttft_ms", 0.0)

    # ── CRM ─────────────────────────────────────────────────────────────────

    async def crm_read(self, user_id: str, key: str) -> Optional[str]:
        try:
            response = await self.http_client.get(f"/crm/{user_id}/{key}")
            if response.status_code == 404:
                return None
            data = response.json()
            return data.get("value")
        except:
            return None

    async def crm_write(self, user_id: str, key: str, value: str) -> bool:
        try:
            response = await self.http_client.post(f"/crm/{user_id}", json={"key": key, "value": value})
            return response.status_code == 200
        except:
            return False

    async def crm_delete(self, user_id: str, key: str) -> bool:
        try:
            response = await self.http_client.delete(f"/crm/{user_id}/{key}")
            return response.status_code == 200
        except:
            return False

    # ── Tools ────────────────────────────────────────────────────────────────

    async def invoke_tool(self, tool_name: str, args: dict, timeout: float = 10.0) -> dict:
        start_time = time.perf_counter()
        try:
            response = await self.http_client.post(f"/tools/{tool_name}", json=args, timeout=timeout)
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if response.status_code >= 400:
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "detail": response.text,
                    "latency_ms": latency_ms
                }
            
            data = response.json()
            data["latency_ms"] = latency_ms
            return data
        except Exception as e:
            return {
                "error": True,
                "status_code": 500,
                "detail": str(e),
                "latency_ms": (time.perf_counter() - start_time) * 1000
            }

    # ── RAG ──────────────────────────────────────────────────────────────────

    async def rag_retrieve(self, query: str, top_k: int = 5) -> dict:
        start_time = time.perf_counter()
        try:
            response = await self.http_client.post("/rag/retrieve", json={"query": query, "top_k": top_k})
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if response.status_code >= 400:
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "detail": response.text,
                    "latency_ms": latency_ms
                }
            
            data = response.json()
            # Gateway returns {"chunks": [...candidate dicts...], "retrieval_ms": N}
            # Each candidate has: chunk_id, text, heading, source, path, fusion_score, etc.
            return {
                "chunks": data.get("chunks", []),
                "retrieval_ms": data.get("retrieval_ms", latency_ms),
            }
        except Exception as e:
            return {
                "error": True,
                "status_code": 500,
                "detail": str(e),
                "latency_ms": (time.perf_counter() - start_time) * 1000
            }

    # ── Debug ────────────────────────────────────────────────────────────────

    async def get_last_tool_calls(self, session_id: str) -> list[dict]:
        start_time = time.perf_counter()
        try:
            response = await self.http_client.get(f"/debug/last_tool_calls/{session_id}")
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if response.status_code >= 400:
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "detail": response.text,
                    "latency_ms": latency_ms
                }
            
            return response.json()
        except Exception as e:
            return {
                "error": True,
                "status_code": 500,
                "detail": str(e),
                "latency_ms": (time.perf_counter() - start_time) * 1000
            }
