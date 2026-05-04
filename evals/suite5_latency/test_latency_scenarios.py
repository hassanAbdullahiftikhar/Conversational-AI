"""
Suite 5: Latency and Throughput - Scenario Benchmarking
Markers: @pytest.mark.suite5
"""
import uuid
import asyncio
import statistics
from pathlib import Path
import pytest
import pytest_asyncio
from utils.metrics import latency_stats

REPORTS = Path(__file__).parent.parent / "reports"

SCENARIOS = [
    {
        "id": "latency_s1",
        "name": "plain_chat",
        "message": "Hello, what can you help me with today?",
        "triggers_rag": False,
        "triggers_tool": False,
        "p90_ttft_limit_ms": 3000,
    },
    {
        "id": "latency_s2",
        "name": "rag_only",
        "message": "How do I pair a Zigbee bulb with Home Assistant using ZHA?",
        "triggers_rag": True,
        "triggers_tool": False,
        "p90_ttft_limit_ms": 5000,
    },
    {
        "id": "latency_s3",
        "name": "tool_only",
        "message": "What is 1234 multiplied by 5678?",
        "triggers_rag": False,
        "triggers_tool": True,
        "p90_ttft_limit_ms": 4000,
    },
    {
        "id": "latency_s4",
        "name": "rag_plus_tool",
        "message": (
            "I have 6 Zigbee devices and 4 Z-Wave devices. "
            "How many devices do I have in total? "
            "Also give me the pairing steps for each protocol."
        ),
        "triggers_rag": True,
        "triggers_tool": True,
        "p90_ttft_limit_ms": 7000,
    },
]

# Can be overridden by env
TRIALS_PER_SCENARIO = 30
P99_E2E_LIMIT_MS = 15000
MAX_OUTLIER_FRACTION = 0.10

_latency_results = {}

@pytest_asyncio.fixture(autouse=True)
async def warmup(api_client):
    """Send warmup messages to fill caches before measurements."""
    for _ in range(3):
        await api_client.chat(session_id=str(uuid.uuid4()), message="Warm up.")
    await asyncio.sleep(1)

@pytest.mark.suite5
@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_latency_scenario(api_client, scenario):
    """Measures TTFT, ITL, and E2E latency for a specific scenario over multiple trials."""
    import os
    trials = int(os.getenv("TRIALS_PER_SCENARIO", TRIALS_PER_SCENARIO))
    
    trial_results = []
    
    for _ in range(trials):
        session_id = str(uuid.uuid4())
        res = await api_client.chat_ws(
            session_id=session_id, 
            messages=[{"role": "user", "content": scenario["message"]}]
        )
        
        if res.get("error"):
            continue
            
        trial_results.append(res)
        # Avoid bursty load during measurement
        await asyncio.sleep(0.5)

    if not trial_results:
        pytest.fail(f"No successful trials for scenario {scenario['id']}")

    ttft_samples = [r["ttft_ms"] for r in trial_results]
    e2e_samples = [r["e2e_ms"] for r in trial_results]
    
    ttft_stats = latency_stats(ttft_samples)
    e2e_stats = latency_stats(e2e_samples)
    
    # Store for later analysis and reporting
    _latency_results[scenario["id"]] = {
        "scenario": scenario,
        "ttft_stats": ttft_stats,
        "e2e_stats": e2e_stats,
        "samples": trial_results
    }
    
    print(f"\nScenario: {scenario['name']}")
    print(f"  TTFT p90: {ttft_stats['p90']}ms (Limit: {scenario['p90_ttft_limit_ms']}ms)")
    print(f"  E2E p99:  {e2e_stats['p99']}ms (Limit: {P99_E2E_LIMIT_MS}ms)")
    
    assert ttft_stats["p90"] <= scenario["p90_ttft_limit_ms"]
    assert e2e_stats["p99"] <= P99_E2E_LIMIT_MS

@pytest.mark.suite5
def test_latency_outlier_analysis():
    """Checks that the fraction of outlier latencies is within acceptable limits."""
    if not _latency_results:
        pytest.skip("No latency results collected.")
        
    for sid, data in _latency_results.items():
        ttft_samples = [r["ttft_ms"] for r in data["samples"]]
        mean = statistics.mean(ttft_samples)
        stddev = statistics.stdev(ttft_samples) if len(ttft_samples) > 1 else 0
        
        outliers = [s for s in ttft_samples if s > mean + 2 * stddev]
        fraction = len(outliers) / len(ttft_samples)
        
        print(f"Scenario {sid}: {len(outliers)} outliers ({fraction:.1%})")
        assert fraction <= MAX_OUTLIER_FRACTION

@pytest.fixture(autouse=True)
def write_latency_report():
    """Writes a detailed latency report for Suite 5."""
    yield
    
    if not _latency_results:
        return
        
    REPORTS.mkdir(parents=True, exist_ok=True)
    import json
    with open(REPORTS / "suite5_latency_results.json", "w") as f:
        # Convert objects to serializable dict
        report = {sid: {
            "name": d["scenario"]["name"],
            "ttft": d["ttft_stats"],
            "e2e": d["e2e_stats"]
        } for sid, d in _latency_results.items()}
        json.dump(report, f, indent=2)
