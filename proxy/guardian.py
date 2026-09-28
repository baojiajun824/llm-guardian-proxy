"""Client for Granite Guardian served through vLLM's OpenAI-compatible API."""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx


CATEGORY_RISKS = (
    ("violence", "violence"),
    ("illegal_activity", "unethical_behavior"),
    ("sexual_content", "sexual_content"),
)


class GuardianUnavailable(RuntimeError):
    """Raised when content cannot be assessed safely."""


@dataclass(frozen=True)
class Assessment:
    risk_score: float
    category: str | None


class GuardianClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        threshold: float,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        self.model = model
        self.threshold = threshold
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def assess(self, user_text: str, assistant_text: str | None = None) -> Assessment:
        messages = [{"role": "user", "content": user_text}]
        if assistant_text is not None:
            messages.append({"role": "assistant", "content": assistant_text})

        risk_score = await self._score(messages, "harm")
        if risk_score < self.threshold:
            return Assessment(risk_score=risk_score, category=None)

        category_scores = [
            (category, await self._score(messages, risk_name))
            for category, risk_name in CATEGORY_RISKS
        ]
        category, category_score = max(category_scores, key=lambda item: item[1])
        return Assessment(
            risk_score=risk_score,
            category=category if category_score >= self.threshold else None,
        )

    async def _score(self, messages: list[dict[str, str]], risk_name: str) -> float:
        request = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 4,
            "logprobs": True,
            "top_logprobs": 20,
            "chat_template_kwargs": {"guardian_config": {"risk_name": risk_name}},
        }
        try:
            response = await self._client.post("/chat/completions", json=request)
            response.raise_for_status()
            return _risk_probability(response.json())
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise GuardianUnavailable(f"Guardian assessment failed: {exc}") from exc


def _risk_probability(payload: dict) -> float:
    choice = payload["choices"][0]
    content = choice.get("message", {}).get("content", "").strip().lower()
    yes_logprob: float | None = None
    no_logprob: float | None = None

    for token in (choice.get("logprobs") or {}).get("content") or []:
        candidates = [token, *(token.get("top_logprobs") or [])]
        for candidate in candidates:
            label = str(candidate.get("token", "")).strip().lower()
            logprob = candidate.get("logprob")
            if not isinstance(logprob, (int, float)):
                continue
            value = float(logprob)
            if label == "yes" and (yes_logprob is None or value > yes_logprob):
                yes_logprob = value
            elif label == "no" and (no_logprob is None or value > no_logprob):
                no_logprob = value

    if yes_logprob is not None and no_logprob is not None:
        highest_logprob = max(yes_logprob, no_logprob)
        yes = math.exp(yes_logprob - highest_logprob)
        no = math.exp(no_logprob - highest_logprob)
        return yes / (yes + no)
    if content == "yes":
        return 1.0
    if content == "no":
        return 0.0
    raise ValueError("Guardian returned neither a score nor a Yes/No label")
