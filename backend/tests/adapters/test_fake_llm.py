from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from my_app.adapters.fake_llm import FakeLlm, FakeLlmCall
from my_app.core.errors import LlmRateLimitError
from my_app.core.llm import LlmCompletion, LlmUsage

if TYPE_CHECKING:
    from my_app.core.llm import LlmMessage

MESSAGES: list[LlmMessage] = [{"role": "user", "content": "hello"}]


def test_fake_llm_records_each_call_with_the_resolved_model():
    fake = FakeLlm(reply="hi", model="fake/default")

    fake.complete(MESSAGES, max_tokens=16, timeout=5)
    fake.complete(MESSAGES, model="other/model", max_tokens=8, timeout=2.5)

    assert fake.calls == [
        FakeLlmCall(
            messages=({"role": "user", "content": "hello"},),
            model="fake/default",
            max_tokens=16,
            timeout=5,
        ),
        FakeLlmCall(
            messages=({"role": "user", "content": "hello"},),
            model="other/model",
            max_tokens=8,
            timeout=2.5,
        ),
    ]


def test_fake_llm_defaults_answer_empty_text_with_zero_usage():
    completion = FakeLlm().complete(MESSAGES, max_tokens=16, timeout=5)

    assert completion == LlmCompletion(
        text="", model="fake/model", finish_reason="stop", usage=LlmUsage(0, 0)
    )


def test_fake_llm_scripted_error_is_raised_after_the_call_is_recorded():
    fake = FakeLlm(error=LlmRateLimitError("slow down"))

    with pytest.raises(LlmRateLimitError, match=r"^slow down$"):
        fake.complete(MESSAGES, max_tokens=16, timeout=5)

    assert len(fake.calls) == 1


def test_fake_llm_invalid_request_records_nothing():
    fake = FakeLlm()

    with pytest.raises(ValueError, match=r"max_tokens must be a positive integer"):
        fake.complete(MESSAGES, max_tokens=0, timeout=5)

    assert fake.calls == []


def test_fake_llm_calls_returns_a_copy():
    fake = FakeLlm()
    fake.complete(MESSAGES, max_tokens=16, timeout=5)

    fake.calls.clear()

    assert len(fake.calls) == 1


def test_fake_llm_recorded_messages_do_not_follow_later_edits():
    fake = FakeLlm()
    messages: list[LlmMessage] = [{"role": "user", "content": "hello"}]
    fake.complete(messages, max_tokens=16, timeout=5)

    messages[0]["content"] = "changed"
    messages.append({"role": "user", "content": "more"})

    assert fake.calls[0].messages == ({"role": "user", "content": "hello"},)


def _traceback_depth(error: BaseException) -> int:
    depth, frame = 0, error.__traceback__
    while frame is not None:
        depth, frame = depth + 1, frame.tb_next
    return depth


def test_fake_llm_scripted_error_traceback_does_not_grow_across_calls():
    fake = FakeLlm(error=LlmRateLimitError("slow down"))
    depths = []
    for _ in range(3):
        with pytest.raises(LlmRateLimitError) as raised:
            fake.complete([{"role": "user", "content": "hi"}], max_tokens=1, timeout=1)
        depths.append(_traceback_depth(raised.value))

    assert depths[0] == depths[1] == depths[2]
