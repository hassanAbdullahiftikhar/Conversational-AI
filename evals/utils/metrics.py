import numpy as np
from typing import List, Tuple, Dict

def precision_at_k(retrieved_ids: List[str], relevant_ids: List[str], k: int) -> float:
    """Fraction of top-k retrieved IDs that appear in relevant_ids. k caps at len(retrieved_ids)."""
    if not retrieved_ids or not relevant_ids:
        return 0.0
    
    k = min(k, len(retrieved_ids))
    top_k = retrieved_ids[:k]
    relevant_set = set(relevant_ids)
    
    hits = sum(1 for doc_id in top_k if doc_id in relevant_set)
    return hits / k

def recall_at_k(retrieved_ids: List[str], relevant_ids: List[str], k: int) -> float:
    """Fraction of relevant_ids found in the top-k retrieved. Returns 0.0 if relevant_ids is empty."""
    if not relevant_ids:
        return 0.0
    if not retrieved_ids:
        return 0.0
    
    k = min(k, len(retrieved_ids))
    top_k = retrieved_ids[:k]
    relevant_set = set(relevant_ids)
    
    hits = sum(1 for doc_id in top_k if doc_id in relevant_set)
    return hits / len(relevant_ids)

def reciprocal_rank(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
    """1 / position_of_first_relevant_id. Returns 0.0 if no relevant ID is found in retrieved_ids."""
    if not retrieved_ids or not relevant_ids:
        return 0.0
    
    relevant_set = set(relevant_ids)
    for i, doc_id in enumerate(retrieved_ids):
        if doc_id in relevant_set:
            return 1.0 / (i + 1)
    return 0.0

def mean_reciprocal_rank(results: List[Tuple[List[str], List[str]]]) -> float:
    """
    MRR across multiple queries.
    results: list of (retrieved_ids, relevant_ids) tuples.
    """
    if not results:
        return 0.0
    
    rr_sum = sum(reciprocal_rank(ret, rel) for ret, rel in results)
    return rr_sum / len(results)

def latency_stats(samples_ms: List[float]) -> Dict[str, float]:
    """
    Returns:
    {
      "mean": float, "median": float,
      "p90": float,  "p99": float,
      "min": float,  "max": float,
      "stddev": float
    }
    All values rounded to 2 decimal places.
    Uses numpy.percentile for p90/p99.
    Raises ValueError if samples_ms is empty.
    """
    if not samples_ms:
        raise ValueError("Cannot calculate stats for empty samples list")
    
    arr = np.array(samples_ms)
    return {
        "mean": round(float(np.mean(arr)), 2),
        "median": round(float(np.median(arr)), 2),
        "p90": round(float(np.percentile(arr, 90)), 2),
        "p99": round(float(np.percentile(arr, 99)), 2),
        "min": round(float(np.min(arr)), 2),
        "max": round(float(np.max(arr)), 2),
        "stddev": round(float(np.std(arr)), 2)
    }

def f1_score(precision: float, recall: float) -> float:
    """Harmonic mean of precision and recall. Returns 0.0 if both are 0."""
    if (precision + recall) == 0:
        return 0.0
    return 2 * (precision * recall) / (precision + recall)
