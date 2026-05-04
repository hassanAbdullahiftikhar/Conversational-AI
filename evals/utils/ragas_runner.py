"""
RagasRunner: Wraps RAGAS 0.4.x evaluation against a local llama.cpp
OpenAI-compatible endpoint (e.g. http://localhost:11434/v1).

Embeddings for RAGAS metrics (answer_relevancy) are computed locally
using sentence-transformers — no embedding API server required.

Metrics evaluated:
  - faithfulness        : Answer is supported by retrieved context
  - answer_relevancy    : Answer addresses the question
  - context_precision   : Retrieved context is relevant to the question
  - context_recall      : Retrieved context covers the ground truth
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

try:
    from datasets import Dataset
except ImportError:
    raise ImportError("Install 'datasets': pip install datasets")

try:
    from ragas import evaluate, RunConfig
    from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
except ImportError:
    raise ImportError("Install 'ragas>=0.4': pip install ragas")

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    raise ImportError("Install 'langchain-openai': pip install langchain-openai")

try:
    from langchain_community.embeddings import HuggingFaceEmbeddings
except ImportError:
    raise ImportError("Install 'langchain-community' and 'sentence-transformers': pip install langchain-community sentence-transformers")


class RagasRunner:
    """
    Evaluates RAG quality using RAGAS 0.4.x with a local LLM endpoint.

    Parameters
    ----------
    llm_endpoint : str
        Base URL of an OpenAI-compatible /v1 endpoint, e.g. ``http://localhost:11434/v1``.
    embeddings_endpoint : str
        Base URL for the embeddings endpoint (can be same server).
    llm_model : str
        Model name sent to the endpoint (only used as an identifier by the server).
    embed_model : str
        Embedding model name (only used as an identifier).
    """

    def __init__(
        self,
        llm_endpoint: str = "http://localhost:11434/v1",
        llm_model: str | None = None,
        embed_model: str | None = None,
    ) -> None:
        llm_model = llm_model or os.getenv("LLM_MODEL", "gemma-4-E4B-it")
        # Local HuggingFace model used for RAGAS embeddings only.
        # Independent from your project's retrieval embeddings.
        embed_model = embed_model or os.getenv(
            "RAGAS_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )

        # LLM: still points at your local llama.cpp / Ollama server
        raw_llm = ChatOpenAI(
            model=llm_model,
            base_url=llm_endpoint,
            api_key="dummy",       # local server; any non-empty string works
            temperature=0,
            max_retries=3,
            timeout=300,           # Increased timeout for local LLMs
        )

        # Embeddings: run fully locally via sentence-transformers (no API needed)
        raw_emb = HuggingFaceEmbeddings(
            model_name=embed_model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

        # RAGAS 0.4.x requires its own wrapper types
        self.llm = LangchainLLMWrapper(raw_llm)
        self.embeddings = LangchainEmbeddingsWrapper(raw_emb)

    # ------------------------------------------------------------------
    def build_dataset(
        self,
        questions: list[str],
        answers: list[str],
        contexts: list[list[str]],
        ground_truths: list[str],
    ) -> Dataset:
        """
        Build a HuggingFace Dataset in the format expected by RAGAS 0.4.x.
        Column names match RAGAS schema exactly:
          user_input, response, retrieved_contexts, reference
        """
        return Dataset.from_dict(
            {
                "user_input": questions,
                "response": answers,
                "retrieved_contexts": contexts,
                "reference": ground_truths,
            }
        )

    # ------------------------------------------------------------------
    def evaluate(self, dataset: Dataset) -> dict[str, Any]:
        """
        Run RAGAS evaluation and return a flat dict of scores.

        Returns
        -------
        dict with keys: faithfulness, answer_relevancy, context_precision, context_recall
        """
        # Force serial execution and single generation to reduce local LLM load
        run_config = RunConfig(
            timeout=300,
            max_workers=1,
        )
        
        # Configure metrics to only expect 1 generation
        faithfulness.n = 1
        answer_relevancy.n = 1
        
        result = evaluate(
            dataset=dataset,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            llm=self.llm,
            embeddings=self.embeddings,
            run_config=run_config,
            raise_exceptions=False,
        )

        scores: dict[str, Any] = {}
        # result is a ragas EvaluationResult; iterate its to_pandas() for safety
        try:
            df = result.to_pandas()
            for metric_name in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if metric_name in df.columns:
                    val = df[metric_name].mean()
                    scores[metric_name] = round(float(val), 4) if not np.isnan(val) else 0.0
                else:
                    scores[metric_name] = 0.0
        except Exception:
            # Fallback: iterate result dict directly
            for k, v in result.items():
                if isinstance(v, (float, np.floating)):
                    scores[k] = round(float(v), 4)
                else:
                    scores[k] = v

        return scores
