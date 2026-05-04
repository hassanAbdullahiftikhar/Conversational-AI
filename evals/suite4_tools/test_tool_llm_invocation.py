"""
Suite 4: Additional Tools - LLM Invocation Accuracy
Markers: @pytest.mark.suite4
"""
import uuid
import pytest
import math
from typing import List, Dict

# Module-level collectors for aggregate reporting
_tool_selection_results = []
_arg_extraction_results = []

@pytest.mark.suite4
@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    {"id": "calc_llm_001", "utterance": "What is 15% of 340?", "expected_tool": "calculator", "expected_result": 51.0, "tolerance": 0.5},

    # --- Added harder calculator cases ---

    {"id": "calc_llm_005", "utterance": "What is (345.6 * 78.9) / 12.3?", "expected_tool": "calculator", "expected_result": 2217.07, "tolerance": 1.0},

    {"id": "calc_llm_007", "utterance": "A car travels 238.7 km using 18.9 liters of fuel. What is the fuel efficiency (km per liter)?", "expected_tool": "calculator", "expected_result": 12.63, "tolerance": 0.1},


    {"id": "calc_llm_009", "utterance": "If 3.75 kg costs $42.60, what is the price per kg?", "expected_tool": "calculator", "expected_result": 11.36, "tolerance": 0.1},

    {"id": "calc_llm_012", "utterance": "What is 0.00345 multiplied by 98765?", "expected_tool": "calculator", "expected_result": 340.74, "tolerance": 0.5},

    {"id": "calc_llm_014", "utterance": "If 12 workers complete a task in 15.5 days, how long would 8 workers take (same rate)?", "expected_tool": "calculator", "expected_result": 23.25, "tolerance": 0.5},

    # --- Existing non-calculator/tool tests ---
    {"id": "search_llm_001", "utterance": "What are the newest features in the latest Home Assistant release?", "expected_tool": "web_search", "requires_recency": True},
    {"id": "url_fetch_001", "utterance": "Summarize this article for me: https://example.com/article", "expected_tool": "url_fetch", "expected_args": {"url": "https://example.com/article"}},
    {"id": "tool_llm_005", "utterance": "What is the capital of France?", "expected_tool": None},
])
async def test_tool_selection_and_args(api_client, case):
    """Verifies that the assistant selects the correct tool and provides valid arguments."""
    session_id = str(uuid.uuid4())
    res = await api_client.chat(session_id=session_id, message=case["utterance"])
    
    tool_calls = res.get("tool_calls", [])
    expected_tool = case["expected_tool"]
    
    # 1. Check Tool Selection
    if expected_tool is None:
        selection_correct = not any(tc["tool_name"] in ["calculator", "web_search", "url_fetch"] for tc in tool_calls)
        _tool_selection_results.append({"id": case["id"], "correct": selection_correct})
        assert selection_correct, f"Unexpected tool call for {case['id']}"
        return

    target_call = next((tc for tc in tool_calls if tc["tool_name"] == expected_tool), None)
    selection_correct = target_call is not None
    _tool_selection_results.append({"id": case["id"], "correct": selection_correct})
    assert selection_correct, f"Expected tool {expected_tool} not called for {case['id']}"

    # 2. Check Argument Extraction
    args = target_call.get("args", {})
    arg_correct = False
    
    if expected_tool == "calculator":
        expression = args.get("expression", "")
        try:
            # Safe eval for testing purposes
            allowed_names = {"sqrt": math.sqrt, "pow": pow, "abs": abs}
            actual_result = eval(expression, {"__builtins__": {}}, allowed_names)
            arg_correct = abs(actual_result - case["expected_result"]) <= case["tolerance"]
        except Exception as e:
            arg_correct = False
            
    elif expected_tool == "web_search":
        query = args.get("query", "")
        # Non-empty and contains at least one keyword
        arg_correct = len(query.strip()) > 5
        
    elif expected_tool == "url_fetch":
        expected_url = case["expected_args"]["url"]
        arg_correct = expected_url.lower() in str(args.get("url", "")).lower()
        
    _arg_extraction_results.append({"id": case["id"], "correct": arg_correct})
    assert arg_correct, f"Argument extraction failed for {case['id']}. Args: {args}"

@pytest.mark.suite4
def test_tool_invocation_accuracy_aggregate():
    """Validates aggregate accuracy across all LLM tool tests."""
    if not _tool_selection_results:
        pytest.skip("No tool selection results collected.")
        
    selection_accuracy = sum(1 for r in _tool_selection_results if r["correct"]) / len(_tool_selection_results)
    
    print(f"\nTool Selection Accuracy: {selection_accuracy:.1%}")
    assert selection_accuracy >= 0.60, f"Selection accuracy {selection_accuracy:.1%} < 60%"
    
    if _arg_extraction_results:
        arg_accuracy = sum(1 for r in _arg_extraction_results if r["correct"]) / len(_arg_extraction_results)
        print(f"Arg Extraction Accuracy: {arg_accuracy:.1%}")
        assert arg_accuracy >= 0.80, f"Arg accuracy {arg_accuracy:.1%} < 80%"
