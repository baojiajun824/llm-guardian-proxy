import json
import math

import httpx
import pytest

from proxy.guardian import GuardianClient, GuardianUnavailable, _risk_probability


def guardian_response(label: str, yes_probability: float) -> dict:
    no_probability = 1 - yes_probability
    return {
        "choices": [
            {
                "message": {"content": label},
                "logprobs": {
                    "content": [
                        {
                            "token": label,
                            "logprob": math.log(
                                yes_probability if label == "Yes" else no_probability
                            ),
                            "top_logprobs": [
                                {"token": "Yes", "logprob": math.log(yes_probability)},
                                {"token": "No", "logprob": math.log(no_probability)},
                            ],
                        }
                    ]
                },
            }
        ]
    }


def test_normalizes_yes_and_no_probabilities() -> None:
    assert _risk_probability(guardian_response("Yes", 0.8)) == pytest.approx(0.8)


def test_probability_normalization_avoids_underflow() -> None:
    payload = guardian_response("Yes", 0.8)
    candidates = payload["choices"][0]["logprobs"]["content"][0]
    candidates["logprob"] = -1000
    candidates["top_logprobs"] = [
        {"token": "Yes", "logprob": -1000},
        {"token": "No", "logprob": -1001},
    ]

    assert _risk_probability(payload) == pytest.approx(1 / (1 + math.exp(-1)))


@pytest.mark.asyncio
async def test_safe_content_stops_after_harm_check() -> None:
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=guardian_response("No", 0.1))

    client = GuardianClient(
        "http://guardian/v1", "guardian", "unused", 0.5, 1, httpx.MockTransport(handler)
    )
    result = await client.assess("Hello")
    await client.close()

    assert result.risk_score == pytest.approx(0.1)
    assert result.category is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_blocked_content_gets_highest_scoring_category() -> None:
    scores = iter([0.9, 0.7, 0.8, 0.6])

    async def handler(request: httpx.Request) -> httpx.Response:
        probability = next(scores)
        return httpx.Response(
            200, json=guardian_response("Yes" if probability >= 0.5 else "No", probability)
        )

    client = GuardianClient(
        "http://guardian/v1", "guardian", "unused", 0.5, 1, httpx.MockTransport(handler)
    )
    result = await client.assess("unsafe")
    await client.close()

    assert result.risk_score == pytest.approx(0.9)
    assert result.category == "illegal_activity"


@pytest.mark.asyncio
async def test_guardian_errors_fail_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = GuardianClient(
        "http://guardian/v1", "guardian", "unused", 0.5, 1, httpx.MockTransport(handler)
    )
    with pytest.raises(GuardianUnavailable):
        await client.assess("Hello")
    await client.close()
