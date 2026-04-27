"""Tool call latency benchmarking."""
import asyncio
import time
import httpx

TOOL_URL = "http://localhost:8001/internal/tool-router/execute"
TOOL_GATEWAY_URL = "http://localhost:8000/internal/tool-router/execute"


async def benchmark_tool(tool: str, args: dict, runs: int = 10, use_gateway: bool = True) -> dict:
    """Benchmark a single tool. Returns avg/p95 latency in ms."""
    url = TOOL_GATEWAY_URL if use_gateway else TOOL_URL
    latencies = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(runs):
            start = time.perf_counter()
            try:
                response = await client.post(
                    url,
                    json={"tool": tool, "arguments": args}
                )
                elapsed = (time.perf_counter() - start) * 1000
                if response.status_code == 200:
                    latencies.append(elapsed)
            except Exception as e:
                print(f"Run {i+1} failed: {e}")

    if not latencies:
        return {"tool": tool, "error": "All runs failed"}

    latencies.sort()
    avg = sum(latencies) / len(latencies)
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    return {
        "tool": tool,
        "runs": len(latencies),
        "avg_ms": round(avg, 1),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(p99, 1),
        "min_ms": round(min(latencies), 1),
        "max_ms": round(max(latencies), 1),
    }


async def run_all_benchmarks():
    """Run benchmarks for all 5 tools."""
    tools = [
        ("search_docs", {"query": "zigbee pairing guide", "top_k_parents": 3}),
        ("web_search", {"query": "home assistant weather integration"}),
        ("calculator", {"expression": "2+2*3"}),
        ("url_fetch", {"url": "https://example.com", "max_chars": 500}),
        ("crm_profile_read", {"include_fields": ["name", "city"]}),
    ]

    results = []
    for tool_name, args in tools:
        print(f"\nBenchmarking {tool_name}...")
        result = await benchmark_tool(tool_name, args)
        print(f"  avg={result.get('avg_ms', 'N/A')}ms, p95={result.get('p95_ms', 'N/A')}ms")
        results.append(result)

    print("\n" + "=" * 60)
    print("TOOL LATENCY SUMMARY")
    print("=" * 60)
    print(f"{'Tool':<20} {'Avg':<10} {'P50':<10} {'P95':<10}")
    print("-" * 60)
    for r in results:
        print(f"{r['tool']:<20} {r.get('avg_ms', 'N/A'):<10} {r.get('p50_ms', 'N/A'):<10} {r.get('p95_ms', 'N/A'):<10}")
    print("=" * 60)

    return results


if __name__ == "__main__":
    asyncio.run(run_all_benchmarks())