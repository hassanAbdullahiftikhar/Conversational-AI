import json
import asyncio
import os
from typing import Any, List, Dict, Optional

class LLMJudge:
    """
    Calls an LLM to score assistant outputs against a rubric.
    Supports Anthropic and OpenAI as backends.
    """

    SYSTEM_PROMPT = (
        "You are an objective evaluator. Score the following strictly according "
        "to the rubric provided. Respond ONLY with valid JSON and nothing else — "
        "no markdown fences, no explanation outside the JSON. "
        'Schema: {"score": int, "reasoning": str, "passed": bool} '
        "Score range: 1 (completely failed) to 5 (fully met). "
        "passed is true if score >= 4."
    )

    def __init__(self, model: str, api_key: str, provider: str = "anthropic", base_url: str | None = None):
        self.model = model
        self.api_key = api_key
        self.provider = provider.lower()
        self.base_url = base_url
        
        if self.provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic
                self.client = AsyncAnthropic(api_key=api_key)
            except ImportError:
                self.client = None
        elif self.provider == "openai":
            try:
                from openai import AsyncOpenAI
                self.client = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
            except ImportError:
                self.client = None
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    async def score(self, rubric: str, context: dict) -> dict:
        """
        Returns {"score": int, "reasoning": str, "passed": bool}.
        Retries up to 3 times on JSON parse failure before raising ValueError.
        Validates that "score" is int 1–5, "passed" is bool.
        """
        if not self.client:
            raise ImportError(f"Client for {self.provider} not initialized. Ensure 'anthropic' or 'openai' package is installed.")

        prompt = f"Rubric: {rubric}\n\nContext to evaluate: {json.dumps(context, indent=2)}"
        
        for attempt in range(3):
            try:
                if self.provider == "anthropic":
                    response = await self.client.messages.create(
                        model=self.model,
                        max_tokens=512,
                        temperature=0,
                        system=self.SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    content = response.content[0].text if response.content else ""
                else:  # openai
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        max_tokens=512,
                        temperature=0,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": prompt}
                        ]
                    )
                    content = response.choices[0].message.content

                # Robust JSON extraction — local LLMs often wrap JSON in extra text
                import re
                content = content.strip() if content else ""
                
                # Guard: empty response from model
                if not content:
                    raise ValueError("Model returned empty response")
                
                json_str = None
                
                # 1. Strip markdown fences
                fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
                if fence_match:
                    json_str = fence_match.group(1).strip()
                
                # 2. Find first {...} block anywhere in the response
                if not json_str:
                    brace_match = re.search(r"\{[^{}]*\}", content)
                    if brace_match:
                        json_str = brace_match.group(0)
                
                # 3. Fall back to raw content
                if not json_str:
                    json_str = content

                data = json.loads(json_str)
                
                # Validation
                score = data.get("score")
                if not isinstance(score, int) or not (1 <= score <= 5):
                    # Try coercing float to int
                    try:
                        score = int(float(score))
                        data["score"] = score
                    except (TypeError, ValueError):
                        raise ValueError(f"Invalid score: {score}")
                
                passed = data.get("passed")
                if not isinstance(passed, bool):
                    data["passed"] = score >= 4
                
                return data

            except (json.JSONDecodeError, ValueError, Exception) as e:
                if attempt == 2:
                    error_msg = f"Failed to get valid JSON response from judge after 3 attempts: {str(e)}"
                    if 'content' in locals():
                        error_msg += f"\nRaw content: {content}"
                    raise ValueError(error_msg)
                await asyncio.sleep(1)

    async def batch_score(
        self,
        items: List[Dict],
        rubric: str,
        max_concurrent: int = 5,
    ) -> List[Dict]:
        """
        Calls score() for each item concurrently with a semaphore of max_concurrent.
        Each item in `items` is passed as `context` to score().
        Returns list in same order as input.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _throttled_score(item):
            async with semaphore:
                return await self.score(rubric, item)

        tasks = [_throttled_score(item) for item in items]
        return await asyncio.gather(*tasks)
