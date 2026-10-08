from __future__ import annotations

import pytest

from my_app.adapters.closed_llm import ClosedLlm
from my_app.core.errors import LlmConfigurationError
from my_app.core.ports import LlmPort


def test_closed_llm_satisfies_the_port():
    assert isinstance(ClosedLlm(), LlmPort)


def test_closed_llm_valid_request_raises_configuration_error_naming_the_key():
    with pytest.raises(
        LlmConfigurationError,
        match=r"^LLM is not configured: set OPENROUTER_API_KEY to enable it$",
    ):
        ClosedLlm().complete(
            [{"role": "user", "content": "hi"}], max_tokens=16, timeout=5
        )


def test_closed_llm_invalid_request_raises_value_error_first():
    with pytest.raises(ValueError, match=r"^messages must not be empty$"):
        ClosedLlm().complete([], max_tokens=16, timeout=5)
