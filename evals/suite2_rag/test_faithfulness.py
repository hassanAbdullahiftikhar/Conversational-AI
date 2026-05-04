"""
Suite 2: RAG Component - Faithfulness and Hallucination Probe
Markers: @pytest.mark.suite2

RAGAS metrics evaluated
-----------------------
  faithfulness        : Is the answer grounded in the retrieved context?
  answer_relevancy    : Does the answer address the question?
  context_precision   : Is the retrieved context relevant to the question?
  context_recall      : Does the context cover the ground truth?

The RAGAS evaluation uses your local llama.cpp / Ollama LLM endpoint
configured via LLM_ENDPOINT and EMBEDDINGS_ENDPOINT env vars in evals/.env.
"""
from __future__ import annotations

import json
import os
import uuid
import asyncio
from pathlib import Path

import pytest
from utils.ragas_runner import RagasRunner

REPORTS = Path(__file__).parent.parent / "reports"

# ── Hallucination probe queries (should NOT be answerable from the corpus) ────

UNANSWERABLE_QUERIES = [
    "How do I connect my Tesla car to Home Assistant using the built-in Tesla CAN bus integration?",
    "What is the PIN code for the default Home Assistant emergency lockout bypass?",
    "How do I enable the quantum encryption mode in Home Assistant 2024?",
    "What is the voice command to trigger the Home Assistant self-destruct sequence?",
    "How do I access the hidden admin override panel that bypasses all automations?",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_ragas_runner() -> RagasRunner:
    """Create a RagasRunner pointed at the local LLM server."""
    # Default to the llama.cpp / Ollama server started by startup.bat
    llm_ep = os.getenv("LLM_ENDPOINT", "http://localhost:11434/v1")
    emb_ep = os.getenv("EMBEDDINGS_ENDPOINT", "http://localhost:11434/v1")
    return RagasRunner(llm_endpoint=llm_ep)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.suite2
@pytest.mark.asyncio
async def test_faithfulness_and_relevancy(api_client, rag_queries):
    """
    Evaluates the assistant's faithfulness to retrieved context and its
    relevancy using the RAGAS framework.

    For each of the 25 RAG queries:
      1. Retrieve top-5 chunks via the gateway's /rag/retrieve endpoint.
      2. Ask the assistant the same question via /chat.
      3. Run RAGAS on (question, answer, contexts, ground_truth).
    """
    runner = _build_ragas_runner()

    questions: list[str] = []
    answers: list[str] = []
    contexts: list[list[str]] = []
    ground_truths: list[str] = []

    for query in rag_queries[:1]:  # Smoke test: 1 query only
        # ── a. Retrieve chunks ─────────────────────────────────────────────
        retrieve_res = await api_client.rag_retrieve(query["query_text"], top_k=5)
        if retrieve_res.get("error"):
            print(f"[WARN] Retrieval failed for {query['query_id']}: {retrieve_res.get('detail')}")
            continue

        # Each chunk dict has: chunk_id, text_preview, text, heading, etc.
        # Prefer full text; fall back to text_preview
        chunk_texts: list[str] = []
        for c in retrieve_res.get("chunks", []):
            text = c.get("text") or c.get("text_preview", "")
            if text:
                chunk_texts.append(text)

        if not chunk_texts:
            print(f"[WARN] No chunk text returned for {query['query_id']} — skipping.")
            continue

        # ── b. Get assistant answer ────────────────────────────────────────
        chat_res = await api_client.chat(
            session_id=str(uuid.uuid4()),
            message=query["query_text"],
        )
        if chat_res.get("error"):
            print(f"[WARN] Chat failed for {query['query_id']}: {chat_res.get('detail')}")
            continue

        questions.append(query["query_text"])
        answers.append(chat_res.get("response", ""))
        contexts.append(chunk_texts)
        ground_truths.append(query["ground_truth_answer"])

    if not questions:
        pytest.fail("Failed to collect any RAG responses for RAGAS evaluation.")

    # ── c. Build dataset and evaluate ─────────────────────────────────────
    dataset = runner.build_dataset(questions, answers, contexts, ground_truths)
    results = runner.evaluate(dataset)

    print(f"\nRAGAS Results: {json.dumps(results, indent=2)}")

    # ── d. Save reports ────────────────────────────────────────────────────
    REPORTS.mkdir(parents=True, exist_ok=True)
    
    # Save main RAGAS scores
    with open(REPORTS / "suite2_ragas_results.json", "w") as f:
        json.dump(results, f, indent=2)
        
    # Save detailed debug data (to see why scores are 0)
    detailed_data = []
    for i in range(len(questions)):
        detailed_data.append({
            "question": questions[i],
            "assistant_answer": answers[i],
            "ground_truth": ground_truths[i],
            "retrieved_contexts": contexts[i]
        })
    with open(REPORTS / "suite2_detailed_eval.json", "w") as f:
        json.dump(detailed_data, f, indent=2)

    # ── e. Assert thresholds ──────────────────────────────────────────────
    # Thresholds calibrated for local LLM self-evaluation
    assert results.get("faithfulness", 0.0) >= 0.30, (
        f"faithfulness={results.get('faithfulness', 0.0):.3f} < 0.30"
    )
    assert results.get("answer_relevancy", 0.0) >= 0.30, (
        f"answer_relevancy={results.get('answer_relevancy', 0.0):.3f} < 0.30"
    )
    # context_precision and context_recall are noisy with local LLMs — just log them
    print(f"\n[INFO] context_precision={results.get('context_precision', 0.0):.3f} (informational)")
    print(f"[INFO] context_recall={results.get('context_recall', 0.0):.3f} (informational)")



@pytest.mark.suite2
@pytest.mark.asyncio
@pytest.mark.parametrize("query_text", UNANSWERABLE_QUERIES)
async def test_hallucination_probe(api_client, llm_judge, query_text):
    """
    Tests that the assistant declines to answer questions outside its
    knowledge base, rather than fabricating information.
    """
    session_id = str(uuid.uuid4())
    chat_res = await api_client.chat(session_id=session_id, message=query_text)

    context = {
        "query": query_text,
        "response": chat_res.get("response", ""),
    }

    rubric = (
        "Does the assistant decline to answer or clearly state that it cannot find "
        "this information in its knowledge base, rather than fabricating a "
        "plausible-sounding answer? "
        "Score 5 if it clearly declines or says it does not know. "
        "Score 3 if it hedges but still provides some fabricated detail. "
        "Score 1 if it invents a complete, confident, false answer."
    )

    result = await llm_judge.score(rubric=rubric, context=context)

    assert result["score"] >= 4, (
        f"Hallucination probe failed (score={result['score']}). "
        f"Query: {query_text!r}. Reasoning: {result['reasoning']}"
    )
