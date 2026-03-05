import json
import os
import statistics
import time

import httpx

URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:2b-q4_K_M")
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "192"))
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.65"))
REQUESTS = int(os.getenv("BENCH_REQUESTS", "10"))
PROMPT = (
    "You are a customer support assistant for an electronics retailer. "
    "A customer says: I placed an order 5 days ago and have not received "
    "a shipping confirmation. What should I do?"
)


def main() -> None:
    rows = []
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)) as client:
        for i in range(REQUESTS):
            start = time.perf_counter()
            response = client.post(
                URL,
                json={
                    "model": MODEL,
                    "prompt": PROMPT,
                    "stream": False,
                    "options": {
                        "num_predict": NUM_PREDICT,
                        "num_ctx": NUM_CTX,
                        "temperature": TEMPERATURE,
                    },
                },
            )
            ttfb = time.perf_counter() - start
            response.raise_for_status()
            body = response.json()
            total = time.perf_counter() - start
            text = str(body.get("response", ""))
            est_tokens = len(text) / 4
            tps = est_tokens / total if total > 0 else 0.0
            rows.append(
                {
                    "request": i + 1,
                    "ttft_seconds": round(ttfb, 4),
                    "total_seconds": round(total, 4),
                    "estimated_tokens_per_sec": round(tps, 4),
                }
            )

    ttft_values = [r["ttft_seconds"] for r in rows]
    total_values = [r["total_seconds"] for r in rows]
    tps_values = [r["estimated_tokens_per_sec"] for r in rows]

    print("\nBenchmark Summary")
    print("-" * 72)
    print(f"{'Metric':<24} {'Min':>12} {'Max':>12} {'Avg':>12}")
    print("-" * 72)
    print(f"{'TTFT (s)':<24} {min(ttft_values):>12.4f} {max(ttft_values):>12.4f} {statistics.mean(ttft_values):>12.4f}")
    print(f"{'Total Time (s)':<24} {min(total_values):>12.4f} {max(total_values):>12.4f} {statistics.mean(total_values):>12.4f}")
    print(f"{'Tokens/sec':<24} {min(tps_values):>12.4f} {max(tps_values):>12.4f} {statistics.mean(tps_values):>12.4f}")

    with open("benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


if __name__ == "__main__":
    main()
