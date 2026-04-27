"""End-to-end RAG + Tools integration test."""
import asyncio
import httpx

TOOL_URL = "http://localhost:8001/internal/tool-router/execute"


async def test_search_docs():
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            TOOL_URL,
            json={"tool": "search_docs", "arguments": {"query": "zigbee pairing guide", "top_k_parents": 3}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        print("✓ search_docs passed")
        return True


async def test_web_search():
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            TOOL_URL,
            json={"tool": "web_search", "arguments": {"query": "home assistant weather"}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        assert len(data.get("result", {}).get("snippets", [])) > 0
        print("✓ web_search passed")
        return True


async def test_calculator():
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            TOOL_URL,
            json={"tool": "calculator", "arguments": {"expression": "2+2*3"}}
        )
        assert response.status_code == 200
        data = response.json()
        result = data.get("result", {}).get("result")
        assert result == 8.0, f"Expected 8.0, got {result}"
        print("✓ calculator passed")
        return True


async def test_url_fetch():
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            TOOL_URL,
            json={"tool": "url_fetch", "arguments": {"url": "https://example.com", "max_chars": 200}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        assert "content" in data.get("result", {})
        print("✓ url_fetch passed")
        return True


async def test_crm_write_read():
    test_session = "test-integration-session"
    async with httpx.AsyncClient(timeout=10.0) as client:
        write_resp = await client.post(
            TOOL_URL,
            json={
                "tool": "crm_profile_write",
                "arguments": {"name": "Test User", "city": "Boston"},
                "session_id": test_session,
            }
        )
        assert write_resp.status_code == 200

        read_resp = await client.post(
            TOOL_URL,
            json={
                "tool": "crm_profile_read",
                "arguments": {"include_fields": ["name", "city"]},
                "session_id": test_session,
            }
        )
        assert read_resp.status_code == 200
        data = read_resp.json()
        profile = data.get("result", {}).get("profile", {})
        assert profile.get("name") == "Test User"
        print("✓ crm_profile_write + read passed")
        return True


async def run_integration_tests():
    print("\n" + "=" * 60)
    print("RAG + TOOLS INTEGRATION TESTS")
    print("=" * 60 + "\n")

    tests = [
        ("search_docs", test_search_docs),
        ("web_search", test_web_search),
        ("calculator", test_calculator),
        ("url_fetch", test_url_fetch),
        ("crm", test_crm_write_read),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            await test_fn()
            passed += 1
        except Exception as e:
            print(f"✗ {name} FAILED: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_integration_tests())
    exit(0 if success else 1)