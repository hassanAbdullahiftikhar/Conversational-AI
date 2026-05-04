"""
Session-scoped fixtures shared across all suites.
Loaded automatically by pytest from evals/conftest.py.
"""
import json
import os
from pathlib import Path
import pytest
import pytest_asyncio
from utils.api_client import ApiClient
from utils.llm_judge import LLMJudge

# ── Load .env file so all JUDGE_* and LLM_ENDPOINT vars are available ────────
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file, override=True)
        print(f"[conftest] Loaded env from {_env_file}")
except ImportError:
    pass  # python-dotenv not installed; rely on shell env vars

DATA = Path(__file__).parent / "data"

# ── URL fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def gateway_url() -> str:
    return os.getenv("GATEWAY_URL", "http://localhost:8000")

@pytest.fixture(scope="session")
def ws_url(gateway_url) -> str:
    return gateway_url.replace("http://", "ws://").replace("https://", "wss://")

# ── Client fixtures ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api_client(gateway_url) -> ApiClient:
    client = ApiClient(gateway_url)
    try:
        yield client
    finally:
        await client.close()

@pytest_asyncio.fixture(scope="session")
async def llm_judge() -> LLMJudge:
    # Defaults are all local — .env overrides these if present
    model    = os.getenv("JUDGE_MODEL", "local-model")
    api_key  = os.getenv("JUDGE_API_KEY", "dummy")
    provider = os.getenv("JUDGE_PROVIDER", "openai")       # openai = local compat
    base_url = os.getenv("JUDGE_BASE_URL", os.getenv("LLM_ENDPOINT", "http://localhost:11434/v1"))
    print(f"[conftest] LLM Judge → provider={provider}, model={model}, base_url={base_url}")
    return LLMJudge(model=model, api_key=api_key, provider=provider, base_url=base_url)

# ── Data fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def dialogues() -> list[dict]:
    with open(DATA / "conversations/dialogues.json") as f:
        return json.load(f)

@pytest.fixture(scope="session")
def rag_queries() -> list[dict]:
    with open(DATA / "rag/queries.json") as f:
        return json.load(f)

@pytest.fixture(scope="session")
def ground_truth_chunks() -> dict[str, str]:
    with open(DATA / "rag/ground_truth_chunks.json") as f:
        return json.load(f)

@pytest.fixture(scope="session")
def crm_test_cases() -> dict:
    with open(DATA / "crm/crm_test_cases.json") as f:
        return json.load(f)

@pytest.fixture(scope="session")
def tool_test_cases() -> dict:
    with open(DATA / "tools/tool_test_cases.json") as f:
        return json.load(f)
