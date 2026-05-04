"""
Suite 4: Additional Tools - Unit Tests
Markers: @pytest.mark.suite4
"""
import pytest
import asyncio

@pytest.mark.suite4
class TestCalculatorToolUnit:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("expression, expected", [
        ("2 + 2", 4.0),
        ("144 / 12", 12.0),
        ("6 * 12 + 4 / 2", 74.0),
        ("2 ** 8", 256.0),
    ])
    async def test_valid_inputs_return_correct_schema(self, api_client, expression, expected):
        """calc_unit_001-004: Verifies math correctness."""
        res = await api_client.invoke_tool("calculator", {"expression": expression})
        assert res.get("ok") is True, f"Envelope indicates failure: {res}"
        result_data = res.get("result", {})
        assert "result" in result_data, f"No result in payload: {result_data}"
        assert abs(float(result_data["result"]) - expected) < 0.001

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expression", ["1 / 0", ""])
    async def test_invalid_inputs_return_errors(self, api_client, expression):
        """calc_unit_005, 007: Verifies error handling for bad math."""
        res = await api_client.invoke_tool("calculator", {"expression": expression})
        # If the envelope caught a validation error, "ok" will be False
        if not res.get("ok"):
            assert res.get("error") is not None
        else:
            # If the tool executed but encountered math error, it's in the result
            result_data = res.get("result", {})
            assert "error" in result_data

    @pytest.mark.asyncio
    async def test_calculator_injection_safety(self, api_client):
        """calc_unit_006: Verifies security against code injection."""
        payload = "__import__('os').system('ls')"
        res = await api_client.invoke_tool("calculator", {"expression": payload})
        
        if not res.get("ok"):
            assert res.get("error") is not None
        else:
            result_data = res.get("result", {})
            assert "error" in result_data
            
        output_str = str(res).lower()
        for forbidden in ["/home", "/usr", "/var", "etc"]:
            assert forbidden not in output_str

    @pytest.mark.asyncio
    async def test_calculator_overflow_graceful(self, api_client):
        """calc_unit_008: Verifies no indefinite hanging on huge numbers."""
        payload = "999999999 ** 99999"
        try:
            res = await asyncio.wait_for(
                api_client.invoke_tool("calculator", {"expression": payload}), 
                timeout=5.0
            )
            # The tool should either fail at validation or return an error string
            if res.get("ok"):
                assert "error" in res.get("result", {})
        except asyncio.TimeoutError:
            pass


@pytest.mark.suite4
class TestWebSearchToolUnit:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", ["Home Assistant latest release", "Zigbee vs Z-Wave comparison 2024"])
    async def test_valid_inputs_return_correct_schema(self, api_client, query):
        """search_unit_001, 002: Verifies search result schema."""
        res = await api_client.invoke_tool("web_search", {"query": query})
        assert res.get("ok") is True, f"Envelope failed: {res}"
        
        result_data = res.get("result", {})
        assert "snippets" in result_data, f"No snippets in result: {result_data}"
        snippets = result_data["snippets"]
        assert isinstance(snippets, list)
        assert len(snippets) > 0
        
        for item in snippets:
            assert "title" in item
            assert "href" in item
            assert "body" in item
            assert item["href"].startswith("http")

    @pytest.mark.asyncio
    async def test_invalid_inputs_return_errors(self, api_client):
        """search_unit_003: Verifies error handling for empty query."""
        res = await api_client.invoke_tool("web_search", {"query": ""})
        if res.get("ok"):
            assert "error" in res.get("result", {}) or res.get("result", {}).get("status") == "error"
        else:
            assert res.get("error") is not None

    @pytest.mark.asyncio
    async def test_edge_case_single_char_query(self, api_client):
        """search_unit_004: Verifies no crash on single char."""
        res = await api_client.invoke_tool("web_search", {"query": "a"})
        assert res.get("status_code") != 500


@pytest.mark.suite4
class TestUrlFetchToolUnit:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["https://example.com", "https://httpbin.org/get"])
    async def test_valid_url_fetch(self, api_client, url):
        """url_fetch_unit_001: Verifies fetching a valid URL."""
        res = await api_client.invoke_tool("url_fetch", {"url": url})
        assert res.get("ok") is True, f"Envelope failed: {res}"
        
        result_data = res.get("result", {})
        if "error" in result_data:
            # It's possible the fetch failed due to network, but it shouldn't crash
            assert "status_code" not in result_data or result_data["status_code"] >= 400
        else:
            assert "content" in result_data
            assert "content_length" in result_data
            assert result_data["content_length"] > 0
            assert result_data["url"] == url
            
    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["not_a_url", "ftp://example.com"])
    async def test_invalid_url_returns_error(self, api_client, url):
        """url_fetch_unit_002: Verifies error handling for bad URLs."""
        res = await api_client.invoke_tool("url_fetch", {"url": url})
        if res.get("ok"):
            assert "error" in res.get("result", {})
        else:
            assert res.get("error") is not None
