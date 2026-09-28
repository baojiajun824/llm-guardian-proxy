"""Parsing and response helpers for the supported Chat Completions subset."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any


class UnsupportedRequest(ValueError):
    """Raised when a request is outside the assignment's supported subset."""


@dataclass(frozen=True)
class ChatContent:
    user_text: str
    assistant_text: str | None = None


def extract_request_content(payload: dict[str, Any]) -> ChatContent:
    if payload.get("stream"):
        raise UnsupportedRequest(
            "Streaming is not supported because responses must be checked before release."
        )
    if payload.get("n", 1) != 1:
        raise UnsupportedRequest("Only one completion is supported")
    if any(field in payload for field in ("tools", "tool_choice", "functions", "function_call")):
        raise UnsupportedRequest("Tool calls are not supported")

    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise UnsupportedRequest("messages must be a list")

    user_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            raise UnsupportedRequest("Only text message content is supported")
        user_parts.append(content)

    if not user_parts:
        raise UnsupportedRequest("At least one user message is required")
    return ChatContent(user_text="\n".join(user_parts))


def extract_response_text(payload: dict[str, Any]) -> str | None:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return content if isinstance(content, str) else None


def blocked_text(subject: str, category: str | None) -> str:
    descriptions = {
        "violence": "a description of violent acts",
        "illegal_activity": "an inquiry on how to perform an illegal activity",
        "sexual_content": "sexual content",
    }
    if category in descriptions:
        return f"The {subject} was blocked because it contained {descriptions[category]}."
    return f"The {subject} was blocked because it is considered toxic."


def chat_completion(message: str, model: str = "guardian-proxy") -> bytes:
    payload = {
        "id": f"chatcmpl-blocked-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": message},
                "finish_reason": "content_filter",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    return json.dumps(payload).encode()


def error_body(message: str, error_type: str = "invalid_request_error") -> bytes:
    return json.dumps({"error": {"message": message, "type": error_type}}).encode()
