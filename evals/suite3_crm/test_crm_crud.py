"""
Suite 3: CRM Tool - CRUD Persistence
Markers: @pytest.mark.suite3
"""

import json
from pathlib import Path
import pytest
import pytest_asyncio

# ─────────────────────────────────────────────
# Load JSON as module-level data
# ─────────────────────────────────────────────

DATA = Path(__file__).parent.parent / "data"

with open(DATA / "crm/crm_test_cases.json") as f:
    CRM_CASES = json.load(f)["crud_tests"]

# ─────────────────────────────────────────────
# Cleanup fixture (tracks real writes)
# ─────────────────────────────────────────────

@pytest_asyncio.fixture
async def crm_cleanup(api_client):
    cleanup_map = {}  # user_id -> set(keys)

    yield cleanup_map

    # teardown
    for user_id, keys in cleanup_map.items():
        for key in keys:
            try:
                await api_client.crm_delete(user_id, key)
            except Exception:
                pass


# ─────────────────────────────────────────────
# Unified CRUD test (create + update + delete)
# ─────────────────────────────────────────────

@pytest.mark.suite3
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    CRM_CASES,
    ids=[c["id"] for c in CRM_CASES]
)
async def test_crm_crud(api_client, crm_cleanup, case):

    user_id = case["user_id"]

    # track user in cleanup map
    if user_id not in crm_cleanup:
        crm_cleanup[user_id] = set()

    # ─────────────────────────────
    # INITIAL DATA (setup state)
    # ─────────────────────────────
    if "initial_data" in case:
        for k, v in case["initial_data"].items():
            await api_client.crm_write(user_id, k, v)
            crm_cleanup[user_id].add(k)

    # ─────────────────────────────
    # CREATE / WRITE / UPDATE
    # (same operation in your API)
    # ─────────────────────────────
    if "write_key" in case:
        await api_client.crm_write(
            user_id,
            case["write_key"],
            case["write_value"]
        )
        crm_cleanup[user_id].add(case["write_key"])

    # ─────────────────────────────
    # DELETE (if required by test case)
    # ─────────────────────────────
    if "delete_key" in case:
        await api_client.crm_delete(user_id, case["delete_key"])
        crm_cleanup[user_id].discard(case["delete_key"])

    # ─────────────────────────────
    # READ + ASSERT
    # ─────────────────────────────
    # ─────────────────────────────
# READ + ASSERT
# ─────────────────────────────

    if "read_key" in case:
        val = await api_client.crm_read(user_id, case["read_key"])
        assert val == case["expected_read_value"]

    elif "reads" in case:
        for r in case["reads"]:
            val = await api_client.crm_read(user_id, r["key"])
            assert val == r["expected"]