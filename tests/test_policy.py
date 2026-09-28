import json

import pytest

from proxy.policy import (
    UnsupportedRequest,
    blocked_text,
    chat_completion,
    extract_request_content,
    extract_response_text,
)


def test_extracts_all_user_messages() -> None:
    payload = {
        "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
    }
    assert extract_request_content(payload).user_text == "first\nsecond"


def test_rejects_streaming_before_content_can_escape() -> None:
    with pytest.raises(UnsupportedRequest, match="Streaming"):
        extract_request_content({"stream": True, "messages": []})


def test_rejects_multimodal_content() -> None:
    with pytest.raises(UnsupportedRequest, match="Only text"):
        extract_request_content({"messages": [{"role": "user", "content": []}]})


def test_rejects_tools() -> None:
    with pytest.raises(UnsupportedRequest, match="Tool calls"):
        extract_request_content({"messages": [{"role": "user", "content": "hello"}], "tools": []})


def test_rejects_multiple_completions() -> None:
    with pytest.raises(UnsupportedRequest, match="one completion"):
        extract_request_content({"messages": [{"role": "user", "content": "hello"}], "n": 2})


def test_reads_assistant_response() -> None:
    payload = {"choices": [{"message": {"content": "answer"}}]}
    assert extract_response_text(payload) == "answer"


def test_blocked_completion_is_sdk_compatible_shape() -> None:
    payload = json.loads(chat_completion(blocked_text("prompt", "violence")))
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["finish_reason"] == "content_filter"
    assert "violent acts" in payload["choices"][0]["message"]["content"]
