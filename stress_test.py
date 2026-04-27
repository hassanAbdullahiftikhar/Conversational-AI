import asyncio
import json
import statistics
import time

import httpx
import websockets

API_BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000/ws/chat"


def sanitize_text(text: str) -> str:
    return " ".join(text.lower().split())


async def create_session(client: httpx.AsyncClient) -> tuple[str, str]:
    resp = await client.post(f"{API_BASE}/api/sessions")
    resp.raise_for_status()
    data = resp.json()
    return data["session_id"], data["token"]


async def send_ws_message(session_id: str, token: str, content: str) -> dict:
    start = time.perf_counter()
    ttft = None
    done = False
    token_count = 0
    error = None
    full = ""
    timings = {}
    source_count = 0

    try:
        async with websockets.connect(f"{WS_BASE}/{session_id}?token={token}") as ws:
            await ws.send(json.dumps({"type": "user_message", "content": content}))
            while True:
                message = await ws.recv()
                data = json.loads(message)
                if data.get("type") == "token":
                    token_count += 1
                    full += str(data.get("content", ""))
                    if ttft is None:
                        ttft = time.perf_counter() - start
                elif data.get("type") == "done":
                    raw_timings = data.get("timings", {})
                    timings = raw_timings if isinstance(raw_timings, dict) else {}
                    raw_sources = data.get("sources", [])
                    if isinstance(raw_sources, list):
                        source_count = sum(1 for item in raw_sources if isinstance(item, dict))
                    done = True
                    break
                elif data.get("type") == "error":
                    error = str(data.get("content", ""))
                    break
    except Exception as exc:
        error = type(exc).__name__

    return {
        "ttft": None if ttft is None else round(ttft, 4),
        "total": round(time.perf_counter() - start, 4),
        "done": done,
        "error": error,
        "token_count": token_count,
        "response_signature": sanitize_text(full)[:80],
        "timings": timings,
        "source_count": source_count,
    }


async def test1_baseline(client: httpx.AsyncClient) -> dict:
    rows = []
    for _ in range(5):
        session_id, tok = await create_session(client)
        result = await send_ws_message(session_id, tok, "How do I configure zigbee2mqtt?")
        rows.append(result)

    ttfts = [r["ttft"] for r in rows if r["ttft"] is not None]
    totals = [r["total"] for r in rows]

    def avg_timing(field: str) -> float | None:
        values = []
        for row in rows:
            raw = row.get("timings", {}).get(field)
            if isinstance(raw, (int, float)):
                values.append(float(raw))
        if not values:
            return None
        return round(statistics.mean(values), 2)

    source_counts = [int(row.get("source_count", 0)) for row in rows]

    return {
        "label": "TEST 1 - Baseline latency",
        "min_ttft": min(ttfts) if ttfts else None,
        "max_ttft": max(ttfts) if ttfts else None,
        "avg_ttft": round(statistics.mean(ttfts), 4) if ttfts else None,
        "min_total": min(totals),
        "max_total": max(totals),
        "avg_total": round(statistics.mean(totals), 4),
        "avg_prompt_build_ms": avg_timing("prompt_build_ms"),
        "avg_model_prefill_ms": avg_timing("model_prefill_ms"),
        "avg_model_eval_ms": avg_timing("model_eval_ms"),
        "avg_tts_synthesis_ms": avg_timing("tts_synthesis_ms"),
        "avg_pipeline_wall_ms": avg_timing("pipeline_wall_ms"),
        "avg_source_count": round(statistics.mean(source_counts), 2) if source_counts else 0.0,
    }


async def test2_concurrent(client: httpx.AsyncClient) -> dict:
    sessions = [await create_session(client) for _ in range(10)]
    started = time.perf_counter()
    results = await asyncio.gather(
        *[send_ws_message(sid, tok, "How do I connect my ESPHome device?") for sid, tok in sessions]
    )
    total_time = time.perf_counter() - started
    success = sum(1 for r in results if r["done"] and not r["error"])
    errors = len(results) - success
    return {
        "label": "TEST 2 - Concurrent sessions",
        "success_count": success,
        "error_count": errors,
        "avg_completion_time": round(total_time / len(results), 4),
    }


async def test3_over_capacity(client: httpx.AsyncClient) -> dict:
    sessions = [await create_session(client) for _ in range(12)]
    results = await asyncio.gather(
        *[send_ws_message(sid, tok, "What is the range of Z-Wave?") for sid, tok in sessions]
    )
    rejected = sum(1 for r in results if r["error"] == "server_at_capacity")
    accepted = len(results) - rejected
    return {
        "label": "TEST 3 - Over-capacity",
        "accepted": accepted,
        "rejected": rejected,
        "pass": rejected >= 2,
    }


async def test4_reset_resilience(client: httpx.AsyncClient) -> dict:
    session_id, tok = await create_session(client)
    first = [
        await send_ws_message(session_id, tok, "My garage plug is offline, what should I do?"),
        await send_ws_message(session_id, tok, "Is it compatible with Home Assistant?"),
        await send_ws_message(session_id, tok, "How do I check the protocol?"),
    ]
    await client.post(f"{API_BASE}/api/sessions/{session_id}/reset?token={tok}")
    after_1 = await send_ws_message(session_id, tok, "How do I pair a Zigbee device?")
    after_2 = await send_ws_message(session_id, tok, "What is ESPHome?")

    pre_signatures = {x["response_signature"] for x in first if x["response_signature"]}
    post_signatures = {after_1["response_signature"], after_2["response_signature"]}
    passed = len(pre_signatures.intersection(post_signatures)) == 0

    return {
        "label": "TEST 4 - Reset resilience",
        "pass": passed,
        "reason": "No overlap between pre-reset and post-reset response signatures" if passed else "Post-reset responses appear context-linked",
    }


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        t1 = await test1_baseline(client)
        t2 = await test2_concurrent(client)
        t3 = await test3_over_capacity(client)
        t4 = await test4_reset_resilience(client)

    print("\nSTRESS TEST SUMMARY")
    print("=" * 72)
    print("TEST 1 - Baseline latency", t1)
    print("TEST 2 - Concurrent sessions", t2)
    print("TEST 3 - Over-capacity", t3)
    print("TEST 4 - Reset resilience", t4)

    output = {
        "test_1": {k: v for k, v in t1.items() if k != "label"},
        "test_2": {k: v for k, v in t2.items() if k != "label"},
        "test_3": {k: v for k, v in t3.items() if k != "label"},
        "test_4": {k: v for k, v in t4.items() if k != "label"},
    }
    with open("stress_test_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
