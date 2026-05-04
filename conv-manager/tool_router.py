from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ddgs import DDGS
from pydantic import BaseModel, Field, ValidationError
import ast
import operator
import httpx

from session_store import SessionStore

try:
    from smart_home_rag.retrieval import RetrievalEngine
except ImportError:
    from .smart_home_rag.retrieval import RetrievalEngine

_CONTROL_TOKEN_RE = re.compile(
    r"<\|turn\|>|<\|/turn\|>|<\|im_start\|>|<\|im_end\|>|<turn\|>|</turn\|>|"
    r"<\|think\|>|<\|/think\|>|<think>.*?</think>",
    re.IGNORECASE | re.DOTALL,
)


def _sanitize_for_llm(text: str) -> str:
    return _CONTROL_TOKEN_RE.sub("", text)


class ToolErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ToolSuccessEnvelope(BaseModel):
    ok: bool = True
    tool: str
    call_id: str
    result: dict[str, Any]
    duration_ms: int


class ToolErrorEnvelope(BaseModel):
    ok: bool = False
    tool: str
    call_id: str
    error: ToolErrorInfo
    duration_ms: int


class CRMProfileReadInput(BaseModel):
    key: str


class CRMProfileWriteInput(BaseModel):
    key: Literal[
        "user_name",
        "city",
        "hub_type",
        "device_count",
        "preferred_protocol"
    ]
    value: str | int | bool


class SearchDocsInput(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    top_k_parents: int = Field(default=3, ge=1, le=8)
    source_filter: str | None = Field(default=None, max_length=80)


class WebSearchInput(BaseModel):
    query: str = Field(min_length=3, max_length=200)


class GetDeviceStatusInput(BaseModel):
    device_id: str = Field(min_length=2, max_length=120)


class CheckDeviceCompatibilityInput(BaseModel):
    device_model: str = Field(min_length=2, max_length=160)
    protocol: str | None = Field(default=None, max_length=40)
    ecosystem: str | None = Field(default=None, max_length=80)


class CalculatorInput(BaseModel):
    expression: str = Field(min_length=1, max_length=200)


class URLFetchInput(BaseModel):
    url: str = Field(min_length=5, max_length=500)
    max_chars: int = Field(default=1000, ge=100, le=5000)


SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval(expr: str) -> float:
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid expression: {e}")

    for child in ast.walk(node):
        if isinstance(child, (ast.Call, ast.Attribute, ast.Compare, ast.IfExp,
                        ast.BoolOp, ast.Not, ast.Invert, ast.Lambda, ast.Subscript)):
            raise ValueError("Function calls and comparisons not allowed")
        if isinstance(child, ast.Name):
            raise ValueError("Variables not allowed")

    return eval(compile(node, "<expr>", "eval"),
               {"__builtins__": {}}, SAFE_OPERATORS)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    input_model: type[BaseModel]
    handler: Callable[[str, BaseModel], dict[str, Any] | Awaitable[dict[str, Any]]]


class ToolRouter:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self._retrieval_engine: RetrievalEngine | None = None
        self._allowed_sources = {"home_assistant", "zigbee2mqtt", "esphome"}
        allowlist_env = os.getenv("DEVICE_ID_ALLOWLIST", "")
        self._device_id_allowlist = {
            item.strip().lower().replace(" ", "_")
            for item in allowlist_env.split(",")
            if item.strip()
        }
        self._device_id_pattern = re.compile(r"^[a-zA-Z0-9_.-]{2,64}$")
        self._blocked_write_tools = {
            "set_device_state",
            "set_scene",
            "toggle_device",
            "arm_alarm",
            "disarm_alarm",
        }
        self._mock_status_map: dict[str, dict[str, Any]] = {
            "living_room_light": {
                "status": "online",
                "state": "off",
                "protocol": "zigbee",
                "last_seen": "2026-04-22T14:30:00Z",
            },
            "kitchen_sensor": {
                "status": "online",
                "state": "active",
                "protocol": "esphome",
                "last_seen": "2026-04-22T14:29:40Z",
            },
            "garage_plug": {
                "status": "offline",
                "state": "unknown",
                "protocol": "z-wave",
                "last_seen": "2026-04-22T12:02:10Z",
            },
        }

        self.registry: dict[str, ToolSpec] = {
            "crm_profile_read": ToolSpec(
                name="crm_profile_read",
                input_model=CRMProfileReadInput,
                handler=self._crm_profile_read,
            ),
            "crm_profile_write": ToolSpec(
                name="crm_profile_write",
                input_model=CRMProfileWriteInput,
                handler=self._crm_profile_write,
            ),
            "search_docs": ToolSpec(
                name="search_docs",
                input_model=SearchDocsInput,
                handler=self._search_docs,
            ),
            "web_search": ToolSpec(
                name="web_search",
                input_model=WebSearchInput,
                handler=self._web_search,
            ),
            "get_device_status": ToolSpec(
                name="get_device_status",
                input_model=GetDeviceStatusInput,
                handler=self._get_device_status,
            ),
            "check_device_compatibility": ToolSpec(
                name="check_device_compatibility",
                input_model=CheckDeviceCompatibilityInput,
                handler=self._check_device_compatibility,
            ),
            "calculator": ToolSpec(
                name="calculator",
                input_model=CalculatorInput,
                handler=self._calculator,
            ),
            "url_fetch": ToolSpec(
                name="url_fetch",
                input_model=URLFetchInput,
                handler=self._url_fetch,
            ),
        }

    async def execute(
        self,
        session_id: str,
        tool: str,
        arguments: dict[str, Any] | None,
        call_id: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        normalized_tool = str(tool or "").strip()
        normalized_call_id = str(call_id or uuid.uuid4().hex)

        if normalized_tool in self._blocked_write_tools:
            return self._error(
                tool=normalized_tool,
                call_id=normalized_call_id,
                code="write_action_not_enabled",
                message=(
                    "Write actions are disabled in v1 pending explicit confirmation and safety gating. "
                    "Use read-only diagnostics first."
                ),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        spec = self.registry.get(normalized_tool)
        if spec is None:
            return self._error(
                tool=normalized_tool or "unknown",
                call_id=normalized_call_id,
                code="tool_not_found",
                message=f"Tool '{normalized_tool}' is not registered.",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            validated = spec.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            return self._error(
                tool=normalized_tool,
                call_id=normalized_call_id,
                code="invalid_arguments",
                message=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            raw_result = spec.handler(session_id, validated)
            if inspect.isawaitable(raw_result):
                result = await raw_result
            else:
                result = raw_result

            envelope = ToolSuccessEnvelope(
                tool=normalized_tool,
                call_id=normalized_call_id,
                result=result,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return envelope.model_dump()
        except Exception as exc:
            return self._error(
                tool=normalized_tool,
                call_id=normalized_call_id,
                code="tool_execution_failed",
                message=f"{type(exc).__name__}: {exc}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def _error(
        self,
        tool: str,
        call_id: str,
        code: str,
        message: str,
        duration_ms: int,
    ) -> dict[str, Any]:
        envelope = ToolErrorEnvelope(
            tool=tool,
            call_id=call_id,
            error=ToolErrorInfo(code=code, message=message, retryable=False),
            duration_ms=duration_ms,
        )
        return envelope.model_dump()

    async def _crm_profile_read(self, session_id: str, args: CRMProfileReadInput) -> dict[str, Any]:
        # During runtime, we might want to resolve user_id from session_id
        # For evals, we just use the user_id if passed in session_id or similar
        # But based on our new API, we need user_id. 
        # Let's assume for now user_id == session_id for simplicity or fetch from session metadata
        user_id = session_id 
        profile = await self.store.get_crm_profile_by_user(user_id)
        return {
            "key": args.key,
            "value": profile.get(args.key),
            "user_id": user_id
        }

    async def _crm_profile_write(self, session_id: str, args: CRMProfileWriteInput) -> dict[str, Any]:
        user_id = session_id
        updated_profile = await self.store.update_crm_profile_by_user(user_id, args.key, args.value)
        return {
            "success": True,
            "key": args.key,
            "value": args.value,
            "user_id": user_id
        }

    def _get_retrieval_engine(self) -> RetrievalEngine:
        if self._retrieval_engine is None:
            embedding_mode = os.getenv("RAG_EMBEDDING_MODE", "hash")
            self._retrieval_engine = RetrievalEngine(embedding_mode=embedding_mode)
        return self._retrieval_engine

    async def _search_docs(self, _session_id: str, args: SearchDocsInput) -> dict[str, Any]:
        if args.source_filter and args.source_filter not in self._allowed_sources:
            raise ValueError(
                f"source_filter '{args.source_filter}' is not in allow-list: {sorted(self._allowed_sources)}"
            )

        engine = self._get_retrieval_engine()
        if not engine.has_corpus:
            return {
                "status": "no_corpus",
                "query": args.query,
                "citations": [],
                "snippets": [],
                "timings_ms": {"total_ms": 0},
            }

        result = await asyncio.to_thread(
            engine.search,
            query=args.query,
            top_k_chunks=max(12, args.top_k_parents * 3),
            top_k_parents=args.top_k_parents,
            source_filter=args.source_filter,
        )
        parents = list(result.get("parents", []))

        citations = [
            {
                "source": str(parent.get("source", "")),
                "path": str(parent.get("path", "")),
                "title": str(parent.get("title", "")),
                "parent_id": str(parent.get("parent_id", "")),
            }
            for parent in parents
        ]
        snippets = [
            {
                "parent_id": str(parent.get("parent_id", "")),
                "text": _sanitize_for_llm(str(parent.get("text", "")))[:420],
            }
            for parent in parents
        ]

        return {
            "status": str(result.get("status", "ok")),
            "query": args.query,
            "citations": citations,
            "snippets": snippets,
            "candidates": result.get("candidates", []),
            "timings_ms": dict(result.get("timings_ms", {})),
        }

    def _get_device_status(self, _session_id: str, args: GetDeviceStatusInput) -> dict[str, Any]:
        key = args.device_id.strip().lower().replace(" ", "_")
        if not self._device_id_pattern.fullmatch(key):
            raise ValueError("device_id format is invalid; use [a-zA-Z0-9_.-], length 2..64")
        if self._device_id_allowlist and key not in self._device_id_allowlist:
            raise ValueError("device_id is not in configured allow-list")

        status = self._mock_status_map.get(
            key,
            {
                "status": "unknown",
                "state": "unknown",
                "protocol": "unknown",
                "last_seen": "unknown",
            },
        )

        return {
            "device_id": args.device_id,
            "status": status["status"],
            "state": status["state"],
            "protocol": status["protocol"],
            "last_seen": status["last_seen"],
            "data_source": "mock",
        }

    def _check_device_compatibility(self, _session_id: str, args: CheckDeviceCompatibilityInput) -> dict[str, Any]:
        haystack = " ".join(
            [
                args.device_model.lower(),
                (args.protocol or "").lower(),
                (args.ecosystem or "").lower(),
            ]
        )

        compatibility = "likely"
        confidence = 0.65
        reasons: list[str] = []

        if "zigbee" in haystack:
            reasons.append("Device/protocol suggests Zigbee support path.")
            confidence = max(confidence, 0.82)
        if "z-wave" in haystack or "zwave" in haystack:
            reasons.append("Device/protocol suggests Z-Wave integration path.")
            confidence = max(confidence, 0.76)
        if "wifi" in haystack or "esphome" in haystack:
            reasons.append("Wi-Fi/ESPHome path is typically compatible with Home Assistant.")
            confidence = max(confidence, 0.8)

        if not reasons:
            reasons.append("Insufficient protocol/model detail for strong compatibility verdict.")
            compatibility = "unknown"
            confidence = 0.4

        recommendations = [
            "Confirm protocol and firmware version from device label or app.",
            "Check adapter/controller support before purchase or pairing.",
        ]

        return {
            "device_model": args.device_model,
            "protocol": args.protocol,
            "ecosystem": args.ecosystem,
            "compatibility": compatibility,
            "confidence": round(confidence, 2),
            "reasons": reasons,
            "recommendations": recommendations,
        }

    def _calculator(self, _session_id: str, args: CalculatorInput) -> dict[str, Any]:
        try:
            result = _safe_eval(args.expression)
            return {
                "expression": args.expression,
                "result": float(result),
            }
        except Exception as e:
            return {
                "expression": args.expression,
                "error": str(e),
            }

    async def _url_fetch(self, _session_id: str, args: URLFetchInput) -> dict[str, Any]:
        import re
        from urllib.parse import urlparse

        try:
            parsed = urlparse(args.url)
            if parsed.scheme not in ("http", "https"):
                return {"error": "Only http/https URLs allowed", "url": args.url}
            if not parsed.netloc:
                return {"error": "Invalid URL format", "url": args.url}
        except Exception as e:
            return {"error": f"URL validation failed: {e}", "url": args.url}

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(args.url)
                response.raise_for_status()
                text = response.text
        except httpx.TimeoutException:
            return {"error": "Request timed out", "url": args.url}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP error: {e}", "url": args.url}
        except Exception as e:
            return {"error": str(e), "url": args.url}

        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = text[:args.max_chars]

        return {
            "url": args.url,
            "status_code": response.status_code,
            "content": text,
            "content_length": len(text),
        }

    async def _web_search(self, _session_id: str, args: WebSearchInput) -> dict[str, Any]:
        started = time.perf_counter()
        
        def run_search():
            with DDGS() as ddgs:
                return list(ddgs.text(args.query, max_results=3))
                
        try:
            results = await asyncio.to_thread(run_search)
        except Exception as exc:
            return {
                "status": "error",
                "query": args.query,
                "error": str(exc),
                "timings_ms": {"total_ms": int((time.perf_counter() - started) * 1000)}
            }
            
        snippets = []
        for r in results:
            if isinstance(r, dict):
                snippets.append({
                    "title": _sanitize_for_llm(str(r.get("title", ""))),
                    "body": _sanitize_for_llm(str(r.get("body", ""))),
                    "href": str(r.get("href", ""))
                })
                
        return {
            "status": "ok",
            "query": args.query,
            "snippets": snippets,
            "timings_ms": {"total_ms": int((time.perf_counter() - started) * 1000)}
        }
