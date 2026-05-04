"""
Suite 3: CRM Tool - LLM Invocation Accuracy
Markers: @pytest.mark.suite3
"""
import uuid
import pytest
from typing import List, Dict

@pytest.mark.suite3
@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    {"id": "crm_llm_001", "utterance": "My name is Alice , i will be using this chatbot alot ", "expected_tool": "crm_profile_write", "expected_key": "user_name", "expected_value": "Alice"},
    {"id": "crm_llm_002", "utterance": "I use Zigbee devices at home", "expected_tool": "crm_profile_write", "expected_key": "preferred_protocol", "expected_value": "zigbee"},
    {"id": "crm_llm_003", "utterance": "My home automation hub is Home Assistant", "expected_tool": "crm_profile_write", "expected_key": "hub_type", "expected_value": "Home Assistant"},
    {"id": "crm_llm_006", "utterance": "I have 12 smart bulbs", "expected_tool": "crm_profile_write", "expected_key": "device_count", "expected_value": "12"},
    {"id": "crm_llm_007", "utterance": "What is the capital of France?", "expected_tool": None, "expected_key": None, "expected_value": None},
])
async def test_crm_llm_invocation_single_turn(api_client, case):
    """Verifies that the assistant calls the correct CRM tool for single-turn utterances."""
    session_id = str(uuid.uuid4())
    res = await api_client.chat(session_id=session_id, message=case["utterance"])
    
    tool_calls = res.get("tool_calls", [])
    expected_tool = case["expected_tool"]
    
    if expected_tool is None:
        # Assert no CRM tool called
        crm_calls = [tc for tc in tool_calls if tc["tool_name"].startswith("crm_")]
        assert not crm_calls, f"Unexpected CRM tool call for {case['id']}"
    else:
        # Find expected tool call
        target_call = next((tc for tc in tool_calls if tc["tool_name"] == expected_tool), None)
        assert target_call, f"Expected {expected_tool} not found in tool_calls for {case['id']}"
        
        args = target_call.get("args", {})
        assert args.get("key") == case["expected_key"]
        assert case["expected_value"].lower() in str(args.get("value")).lower()

@pytest.mark.suite3
@pytest.mark.asyncio
async def test_crm_llm_invocation_multi_turn(api_client):
    """
    crm_llm_004 & 005: Verifies assistant can recall information using CRM read.
    """
    session_id = str(uuid.uuid4())
    history = []
    
    # 1. Setup turn: provide info
    res1 = await api_client.chat(session_id=session_id, message="My name is Alice")
    history.append({"role": "user", "content": "My name is Alice"})
    history.append({"role": "assistant", "content": res1.get("response", "")})
    
    # 2. Recall turn: ask about info
    res2 = await api_client.chat(session_id=session_id, message="What's my name?", history=history)
    
    # Check tool call
    tool_calls = res2.get("tool_calls", [])
    read_call = next((tc for tc in tool_calls if tc["tool_name"] == "crm_profile_read"), None)
    assert read_call, "Expected crm_profile_read not found in second turn."
    assert read_call.get("args", {}).get("key") == "user_name"
    
    # Check response content
    assert "Alice" in res2.get("response", "")
