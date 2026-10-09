"""The one contract every ``LlmPort`` implementation that can complete must pass.

A new adapter joins by adding one ``pytest.param`` to ``LLM_FACTORIES``. The
OpenRouter adapter runs over ``httpx.MockTransport`` serving OpenRouter's
documented response shape: the suite never calls the network, which would bill
and flake. ``ClosedLlm`` never completes, so it is not here; it has its own file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from my_app.adapters.fake_llm import FakeLlm
from my_app.adapters.openrouter import OpenRouterLlm
from my_app.core.llm import LlmUsage
from my_app.core.ports import LlmPort

if TYPE_CHECKING:
    from collections.abc import Callable

    from my_app.core.llm import LlmMessage

CONFIGURED_MODEL = "test/default"
ISSUE_MESSAGES: list[LlmMessage] = [{"role": "user", "content": "hello"}]


@dataclass(frozen=True, slots=True)
class _Harness:
    """A port scripted to answer "hi" with usage (3, 1), and what it was sent."""

    port: LlmPort
    requests_sent: Callable[[], int]
    sent_messages: Callable[[], list[dict[str, str]]]


def _fake() -> _Harness:
    fake = FakeLlm(reply="hi", model=CONFIGURED_MODEL, usage=LlmUsage(3, 1))
    return _Harness(
        port=fake,
        requests_sent=lambda: len(fake.calls),
        sent_messages=lambda: [
            {"role": message["role"], "content": message["content"]}
            for message in fake.calls[-1].messages
        ],
    )


def _openrouter() -> _Harness:
    bodies: list[dict[str, object]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(
            200,
            json={
                "id": "gen-1",
                "object": "chat.completion",
                "created": 1_760_000_000,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hi"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                },
            },
        )

    def _sent_messages() -> list[dict[str, str]]:
        messages = bodies[-1]["messages"]
        assert isinstance(messages, list)
        return messages

    port = OpenRouterLlm(
        "test-key", model=CONFIGURED_MODEL, transport=httpx.MockTransport(_handler)
    )
    return _Harness(
        port=port, requests_sent=lambda: len(bodies), sent_messages=_sent_messages
    )


LLM_FACTORIES = [
    pytest.param(_fake, id="fake"),
    pytest.param(_openrouter, id="openrouter"),
]


@pytest.fixture(params=LLM_FACTORIES)
def harness(request):
    return request.param()


def test_llm_adapter_implements_the_port(harness):
    assert isinstance(harness.port, LlmPort)


def test_complete_issue_example_returns_text_usage_and_model(harness):
    completion = harness.port.complete(
        ISSUE_MESSAGES, model="x", max_tokens=16, timeout=5
    )

    assert completion.text == "hi"
    assert completion.usage == LlmUsage(3, 1)
    assert completion.model == "x"
    assert completion.finish_reason == "stop"
    assert harness.requests_sent() == 1


def test_complete_without_model_uses_the_configured_model(harness):
    completion = harness.port.complete(ISSUE_MESSAGES, max_tokens=16, timeout=5)

    assert completion.model == CONFIGURED_MODEL


def test_complete_unicode_content_is_sent_unchanged(harness):
    messages: list[LlmMessage] = [
        {"role": "system", "content": "日本語で答えて"},
        {"role": "user", "content": "こんにちは 👋🏽"},
    ]

    harness.port.complete(messages, max_tokens=16, timeout=5)

    assert harness.sent_messages() == [
        {"role": "system", "content": "日本語で答えて"},
        {"role": "user", "content": "こんにちは 👋🏽"},
    ]


@pytest.mark.parametrize(
    ("arguments", "pattern"),
    [
        pytest.param({"messages": []}, r"messages must not be empty", id="no-messages"),
        pytest.param(
            {"messages": [{"role": "tool", "content": "x"}]},
            r"role must be one of",
            id="bad-role",
        ),
        pytest.param(
            {"messages": [{"content": "x"}]}, r"role must be one of", id="no-role"
        ),
        pytest.param(
            {"messages": [{"role": "user", "content": None}]},
            r"content must be a string",
            id="none-content",
        ),
        pytest.param(
            {"messages": [{"role": "user"}]},
            r"content must be a string",
            id="no-content",
        ),
        pytest.param(
            {"messages": "hello"}, r"messages must be a sequence", id="str-messages"
        ),
        pytest.param(
            {"messages": b"hello"}, r"messages must be a sequence", id="bytes-messages"
        ),
        pytest.param(
            {"messages": 42}, r"messages must be a sequence", id="int-messages"
        ),
        pytest.param(
            {"messages": ["hello"]},
            r"messages\[0\] must be a mapping",
            id="str-message",
        ),
        pytest.param(
            {"messages": [{"role": "user", "content": "lone \ud800 surrogate"}]},
            r"messages\[0\] content must be encodable as UTF-8",
            id="surrogate-content",
        ),
        pytest.param({"model": 42}, r"model must be a string", id="int-model"),
        pytest.param(
            {"model": "x\udc00"},
            r"model must be encodable as UTF-8",
            id="surrogate-model",
        ),
        pytest.param({"model": ""}, r"non-blank model id", id="empty-model"),
        pytest.param({"model": "  "}, r"non-blank model id", id="blank-model"),
        pytest.param({"max_tokens": 0}, r"max_tokens must be", id="zero-tokens"),
        pytest.param({"max_tokens": -1}, r"max_tokens must be", id="negative-tokens"),
        pytest.param({"max_tokens": True}, r"max_tokens must be", id="bool-tokens"),
        pytest.param({"max_tokens": 1.5}, r"max_tokens must be", id="float-tokens"),
        pytest.param({"timeout": 0}, r"timeout must be", id="zero-timeout"),
        pytest.param({"timeout": -1}, r"timeout must be", id="negative-timeout"),
        pytest.param({"timeout": float("nan")}, r"timeout must be", id="nan-timeout"),
        pytest.param({"timeout": float("inf")}, r"timeout must be", id="inf-timeout"),
        pytest.param({"timeout": True}, r"timeout must be", id="bool-timeout"),
    ],
)
def test_complete_invalid_argument_raises_before_any_request(
    harness, arguments, pattern
):
    # Any: the cases replace arguments with values of the wrong type on purpose.
    call: dict[str, Any] = {
        "messages": ISSUE_MESSAGES,
        "max_tokens": 16,
        "timeout": 5,
        **arguments,
    }

    with pytest.raises(ValueError, match=pattern):
        harness.port.complete(**call)

    assert harness.requests_sent() == 0


def test_complete_one_shot_iterator_of_messages_is_sent_whole(harness):
    messages = iter([{"role": "user", "content": "hello"}])

    harness.port.complete(messages, max_tokens=16, timeout=5)

    assert harness.sent_messages() == [{"role": "user", "content": "hello"}]
