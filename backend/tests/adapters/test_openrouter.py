"""What only the OpenRouter adapter does: its wire format, retries, and deadline.

Every test serves the provider from ``httpx.MockTransport`` and runs on a fake
clock whose ``sleep`` records the delay and advances time, so no test touches
the network or waits.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

from my_app.adapters.openrouter import (
    MAX_RESPONSE_BYTES,
    OPENROUTER_CHAT_COMPLETIONS_URL,
    OpenRouterLlm,
)
from my_app.core.errors import (
    LlmConfigurationError,
    LlmError,
    LlmProviderError,
    LlmRateLimitError,
    LlmTimeoutError,
)
from my_app.core.llm import LlmCompletion, LlmUsage

if TYPE_CHECKING:
    from collections.abc import Iterator

    from my_app.core.llm import LlmMessage

API_KEY = "test-key"
MODEL = "test/default"
MESSAGES: list[LlmMessage] = [{"role": "user", "content": "hello"}]
# The provider's own error text can echo the prompt, so no message may carry it.
PROVIDER_ERROR_TEXT = "prompt echo: hello"
START = 1000.0


class _FakeClock:
    """``monotonic`` reads ``now``; ``sleep`` records the delay and advances it."""

    def __init__(self) -> None:
        self.now = START
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _Provider:
    """Serve scripted replies in order, repeating the last; record each request.

    A reply is an ``httpx.Response``, or an ``httpx`` exception class raised
    with the request, as the real transport would.
    """

    def __init__(self, *replies: httpx.Response | type[httpx.TransportError]) -> None:
        self._replies = replies
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self._replies[min(len(self.requests), len(self._replies)) - 1]
        if isinstance(reply, httpx.Response):
            return reply
        msg = "simulated transport failure"
        raise reply(msg, request=request)


def _completion_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 1_760_000_000,
        "model": "provider/answered",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "native_finish_reason": "stop",
                "message": {"role": "assistant", "content": "hi"},
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }
    body.update(overrides)
    return body


def _ok(**overrides: object) -> httpx.Response:
    return httpx.Response(200, json=_completion_body(**overrides))


def _status(code: int, headers: dict[str, str] | None = None) -> httpx.Response:
    error = {"error": {"code": code, "message": PROVIDER_ERROR_TEXT}}
    return httpx.Response(code, json=error, headers=headers)


def _chain(error: BaseException) -> list[BaseException]:
    """Return ``error`` and every exception chained to it, causes and contexts."""
    seen: list[BaseException] = []
    pending: list[BaseException | None] = [error]
    while pending:
        current = pending.pop()
        if current is None or any(current is known for known in seen):
            continue
        seen.append(current)
        pending.extend([current.__cause__, current.__context__])
    return seen


def _assert_never_carries(error: BaseException, *secrets: str) -> None:
    """Fail when any secret shows in the str, repr, or args of the whole chain."""
    for linked in _chain(error):
        shown = [str(linked), repr(linked), *(repr(arg) for arg in linked.args)]
        for secret in secrets:
            assert not any(secret in text for text in shown), linked


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock()


@pytest.fixture
def make_llm(clock):
    def _make(provider: _Provider, *, max_retries: int = 2) -> OpenRouterLlm:
        return OpenRouterLlm(
            API_KEY,
            model=MODEL,
            max_retries=max_retries,
            transport=httpx.MockTransport(provider),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

    return _make


def _complete(llm: OpenRouterLlm, *, timeout: float = 30) -> LlmCompletion:
    return llm.complete(MESSAGES, max_tokens=16, timeout=timeout)


# --- construction ---------------------------------------------------------


@pytest.mark.parametrize(
    "api_key",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
    ],
)
def test_openrouter_llm_without_key_raises_configuration_error(api_key):
    with pytest.raises(
        LlmConfigurationError,
        match=r"^LLM is not configured: set OPENROUTER_API_KEY to enable it$",
    ):
        OpenRouterLlm(api_key, model=MODEL)


@pytest.mark.parametrize("model", [pytest.param("", id="empty"), pytest.param(" ")])
def test_openrouter_llm_blank_model_raises_value_error(model):
    with pytest.raises(ValueError, match=r"^model must be a non-blank model id, got "):
        OpenRouterLlm(API_KEY, model=model)


@pytest.mark.parametrize(
    "max_retries",
    [pytest.param(-1, id="negative"), pytest.param(True, id="bool")],
)
def test_openrouter_llm_invalid_max_retries_raises_value_error(max_retries):
    with pytest.raises(
        ValueError, match=r"^max_retries must be a non-negative integer, got "
    ):
        OpenRouterLlm(API_KEY, model=MODEL, max_retries=max_retries)


@pytest.mark.parametrize(
    "api_key",
    [
        pytest.param("sk-or-v1-s\u00e9cret", id="non-ascii"),
        pytest.param("sk-or-v1-\u5bc6\u9470", id="cjk"),
        pytest.param("sk-or-v1\x00secret", id="control"),
        pytest.param("sk-or-v1 secret", id="inner-space"),
    ],
)
def test_openrouter_llm_key_not_a_header_value_raises_configuration_error(api_key):
    with pytest.raises(
        LlmConfigurationError, match=r"visible ASCII characters"
    ) as raised:
        OpenRouterLlm(api_key, model=MODEL)

    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    _assert_never_carries(raised.value, api_key, api_key.strip()[9:])


@pytest.mark.parametrize(
    ("proxy", "cause"),
    [
        pytest.param(
            "socks5://user:proxy-secret@proxy.invalid:1080", "ImportError", id="socks"
        ),
        pytest.param(
            "ftp://user:proxy-secret@proxy.invalid:21", "ValueError", id="bad-scheme"
        ),
    ],
)
@pytest.mark.parametrize("variable", ["HTTPS_PROXY", "ALL_PROXY"])
def test_complete_unusable_proxy_setting_raises_configuration_error(
    monkeypatch, proxy, cause, variable
):
    for name in (
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(variable, proxy)
    # No transport: httpx reads proxies from the environment only for its own
    # transport. The client fails while it is built, before any connection.
    llm = OpenRouterLlm(API_KEY, model=MODEL, sleep=lambda _: None)

    with pytest.raises(LlmConfigurationError, match=rf"\({cause}\)$") as raised:
        _complete(llm)

    assert "proxy.invalid" not in str(raised.value)
    assert "proxy-secret" not in str(raised.value)


def test_openrouter_llm_model_property_is_the_configured_model():
    assert OpenRouterLlm(API_KEY, model=MODEL).model == MODEL


# --- the request ----------------------------------------------------------


def test_complete_posts_the_chat_completion_request(make_llm):
    provider = _Provider(_ok())

    make_llm(provider).complete(MESSAGES, model="x", max_tokens=16, timeout=30)

    (request,) = provider.requests
    assert request.method == "POST"
    assert str(request.url) == OPENROUTER_CHAT_COMPLETIONS_URL
    assert request.headers["Authorization"] == "Bearer test-key"
    assert json.loads(request.content) == {
        "model": "x",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 16,
        "stream": False,
    }


def test_complete_strips_the_key_before_sending_it():
    provider = _Provider(_ok())
    llm = OpenRouterLlm(
        "  test-key\n", model=MODEL, transport=httpx.MockTransport(provider)
    )

    _complete(llm)

    assert provider.requests[0].headers["Authorization"] == "Bearer test-key"


def test_complete_sends_only_role_and_content_of_each_message(make_llm):
    provider = _Provider(_ok())
    # Parsed JSON, as a caller might pass it: typed Any, with a key LlmMessage lacks.
    messages = json.loads('[{"role": "user", "content": "hello", "name": "ignored"}]')

    make_llm(provider).complete(messages, max_tokens=16, timeout=30)

    body = json.loads(provider.requests[0].content)
    assert body["messages"] == [{"role": "user", "content": "hello"}]


def test_complete_each_attempt_times_out_at_the_remaining_budget(make_llm):
    provider = _Provider(_status(429), _ok())

    _complete(make_llm(provider), timeout=30)

    budgets = [request.extensions["timeout"] for request in provider.requests]
    assert budgets == [
        {"connect": 30.0, "read": 30.0, "write": 30.0, "pool": 30.0},
        {"connect": 29.5, "read": 29.5, "write": 29.5, "pool": 29.5},
    ]


# --- a successful answer --------------------------------------------------


def test_complete_success_returns_the_parsed_completion(make_llm):
    completion = _complete(make_llm(_Provider(_ok())))

    assert completion == LlmCompletion(
        text="hi",
        model="provider/answered",
        finish_reason="stop",
        usage=LlmUsage(3, 1),
    )


def test_complete_finish_reason_length_is_returned_as_is(make_llm):
    choice = {
        "index": 0,
        "finish_reason": "length",
        "message": {"role": "assistant", "content": "hi"},
    }

    completion = _complete(make_llm(_Provider(_ok(choices=[choice]))))

    assert completion.finish_reason == "length"


def test_complete_missing_finish_reason_is_none(make_llm):
    choice = {"index": 0, "message": {"role": "assistant", "content": "hi"}}

    completion = _complete(make_llm(_Provider(_ok(choices=[choice]))))

    assert completion.finish_reason is None


def test_complete_empty_content_is_an_empty_text(make_llm):
    choice = {"index": 0, "message": {"role": "assistant", "content": ""}}

    assert _complete(make_llm(_Provider(_ok(choices=[choice])))).text == ""


def _without(key: str) -> httpx.Response:
    body = _completion_body()
    del body[key]
    return httpx.Response(200, json=body)


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_without("model"), id="missing"),
        pytest.param(_ok(model="  "), id="blank"),
        pytest.param(_ok(model=42), id="not-a-string"),
    ],
)
def test_complete_without_answered_model_reports_the_requested_one(make_llm, reply):
    completion = make_llm(_Provider(reply)).complete(
        MESSAGES, model="x", max_tokens=16, timeout=30
    )

    assert completion.model == "x"


# --- REQ-004: rate limiting and the retry bound ----------------------------


def test_complete_429_every_attempt_raises_rate_limit_after_three_requests(
    make_llm, clock
):
    provider = _Provider(_status(429))

    with pytest.raises(
        LlmRateLimitError,
        match=r"^The LLM provider is rate-limiting requests \(HTTP 429\)$",
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 3
    assert clock.sleeps == [0.5, 1.0]


def test_complete_429_then_200_succeeds_on_the_second_request(make_llm, clock):
    provider = _Provider(_status(429), _ok())

    completion = _complete(make_llm(provider))

    assert completion.text == "hi"
    assert len(provider.requests) == 2
    assert clock.sleeps == [0.5]


def test_complete_with_no_retries_sends_one_request(make_llm, clock):
    provider = _Provider(_status(429))

    with pytest.raises(LlmRateLimitError, match=r"HTTP 429"):
        _complete(make_llm(provider, max_retries=0))

    assert len(provider.requests) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("retry_after", "sleeps"),
    [
        pytest.param("2", [2.0, 2.0], id="seconds"),
        pytest.param("8", [8.0, 8.0], id="at-the-cap"),
        pytest.param("0", [0.0, 0.0], id="zero"),
        pytest.param("abc", [0.5, 1.0], id="unparsable"),
        pytest.param("Wed, 21 Oct 2026 07:28:00 GMT", [0.5, 1.0], id="http-date"),
        pytest.param("-1", [0.5, 1.0], id="negative"),
        pytest.param("nan", [0.5, 1.0], id="nan"),
    ],
)
def test_complete_retry_after_header_sets_the_delay(
    make_llm, clock, retry_after, sleeps
):
    provider = _Provider(_status(429, {"Retry-After": retry_after}))

    with pytest.raises(LlmRateLimitError, match=r"HTTP 429"):
        _complete(make_llm(provider), timeout=60)

    assert clock.sleeps == sleeps


@pytest.mark.parametrize(
    ("retry_after", "sleeps"),
    [
        pytest.param("2", [2.0, 2.0], id="seconds"),
        pytest.param("8", [8.0, 8.0], id="at-the-cap"),
    ],
)
def test_complete_503_retry_after_within_the_cap_sets_the_delay(
    make_llm, clock, retry_after, sleeps
):
    provider = _Provider(_status(503, {"Retry-After": retry_after}))

    with pytest.raises(LlmProviderError, match=r"^The LLM provider returned HTTP 503$"):
        _complete(make_llm(provider), timeout=60)

    assert len(provider.requests) == 3
    assert clock.sleeps == sleeps


def test_complete_502_retry_after_is_ignored_for_the_computed_backoff(make_llm, clock):
    provider = _Provider(_status(502, {"Retry-After": "5"}))

    with pytest.raises(LlmProviderError, match=r"^The LLM provider returned HTTP 502$"):
        _complete(make_llm(provider), timeout=60)

    assert len(provider.requests) == 3
    assert clock.sleeps == [0.5, 1.0]


@pytest.mark.parametrize(
    ("status", "error"),
    [
        pytest.param(429, LlmRateLimitError, id="429"),
        pytest.param(503, LlmProviderError, id="503"),
    ],
)
@pytest.mark.parametrize("retry_after", ["9", "8.5"])
def test_complete_retry_after_above_the_cap_ends_the_call_at_once(
    make_llm, clock, status, error, retry_after
):
    provider = _Provider(_status(status, {"Retry-After": retry_after}))

    with pytest.raises(error, match=rf"HTTP {status}"):
        _complete(make_llm(provider), timeout=60)

    assert len(provider.requests) == 1
    assert clock.sleeps == []


def test_complete_backoff_that_would_reach_the_deadline_raises_without_sleeping(
    make_llm, clock
):
    provider = _Provider(_status(429))

    with pytest.raises(LlmRateLimitError, match=r"HTTP 429"):
        _complete(make_llm(provider), timeout=0.5)

    assert len(provider.requests) == 1
    assert clock.sleeps == []


def test_complete_second_backoff_past_the_deadline_raises_the_last_error(
    make_llm, clock
):
    provider = _Provider(_status(429), _status(503))

    with pytest.raises(LlmProviderError, match=r"^The LLM provider returned HTTP 503$"):
        _complete(make_llm(provider), timeout=1.2)

    assert len(provider.requests) == 2
    assert clock.sleeps == [0.5]


# --- REQ-005: the deadline -------------------------------------------------


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(httpx.ReadTimeout, id="read"),
        pytest.param(httpx.ConnectTimeout, id="connect"),
        pytest.param(httpx.WriteTimeout, id="write"),
        pytest.param(httpx.PoolTimeout, id="pool"),
    ],
)
def test_complete_transport_timeout_raises_timeout_error_without_retry(
    make_llm, exception
):
    provider = _Provider(exception)

    with pytest.raises(
        LlmTimeoutError, match=r"^The LLM request did not finish within 30 seconds$"
    ) as raised:
        _complete(make_llm(provider), timeout=30)

    assert len(provider.requests) == 1
    assert isinstance(raised.value.__cause__, exception)


def test_complete_body_streamed_past_the_deadline_raises_timeout_error(make_llm, clock):
    def _slow_body() -> Iterator[bytes]:
        payload = json.dumps(_completion_body()).encode()
        yield payload[:10]
        clock.now += 31
        yield payload[10:]

    provider = _Provider(httpx.Response(200, content=_slow_body()))

    with pytest.raises(
        LlmTimeoutError, match=r"^The LLM request did not finish within 30 seconds$"
    ):
        _complete(make_llm(provider), timeout=30)

    assert len(provider.requests) == 1


def test_complete_headers_arriving_past_the_deadline_raise_before_the_body_is_read(
    make_llm, clock
):
    body_read: list[bool] = []

    def _body() -> Iterator[bytes]:
        body_read.append(True)
        yield json.dumps(_completion_body()).encode()

    class _LateHeadersProvider(_Provider):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            clock.now += 31
            return super().__call__(request)

    provider = _LateHeadersProvider(httpx.Response(200, content=_body()))

    with pytest.raises(
        LlmTimeoutError, match=r"^The LLM request did not finish within 30 seconds$"
    ):
        _complete(make_llm(provider), timeout=30)

    assert body_read == []
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    ("exception", "error", "pattern"),
    [
        pytest.param(
            httpx.ReadError, LlmProviderError, r"could not be reached$", id="read"
        ),
        pytest.param(
            httpx.RemoteProtocolError,
            LlmProviderError,
            r"could not be reached$",
            id="remote-protocol",
        ),
        pytest.param(
            httpx.ReadTimeout, LlmTimeoutError, r"within 30 seconds$", id="timeout"
        ),
    ],
)
def test_complete_transport_error_mid_body_is_mapped_and_not_retried(
    make_llm, clock, exception, error, pattern
):
    def _broken_body() -> Iterator[bytes]:
        yield b'{"id": "gen-1",'
        msg = "connection lost mid-body"
        raise exception(msg)

    provider = _Provider(httpx.Response(200, content=_broken_body()))

    with pytest.raises(error, match=pattern) as raised:
        _complete(make_llm(provider), timeout=30)

    assert len(provider.requests) == 1
    assert clock.sleeps == []
    assert isinstance(raised.value.__cause__, exception)


def test_complete_time_spent_in_attempts_counts_against_the_budget(make_llm, clock):
    class _SlowProvider(_Provider):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            clock.now += 0.4
            return super().__call__(request)

    provider = _SlowProvider(_status(429))

    # 0.4 s attempt + 0.5 s backoff leaves 0.1 s for the second attempt, which
    # takes 0.4 s more; no 1.0 s backoff fits after it.
    with pytest.raises(LlmRateLimitError, match=r"HTTP 429"):
        _complete(make_llm(provider), timeout=1.0)

    assert clock.sleeps == [0.5]
    assert len(provider.requests) == 2
    assert provider.requests[1].extensions["timeout"]["read"] == pytest.approx(0.1)


def test_complete_no_budget_left_after_a_backoff_raises_timeout_error(make_llm, clock):
    class _ClockJumpingSleep:
        def __call__(self, seconds: float) -> None:
            clock.sleeps.append(seconds)
            clock.now += 10  # a sleep that overran: nothing is left of the budget

    provider = _Provider(_status(429), _ok())
    llm = OpenRouterLlm(
        API_KEY,
        model=MODEL,
        transport=httpx.MockTransport(provider),
        sleep=_ClockJumpingSleep(),
        monotonic=clock.monotonic,
    )

    with pytest.raises(LlmTimeoutError, match=r"did not finish within 5 seconds"):
        _complete(llm, timeout=5)

    assert len(provider.requests) == 1


@pytest.mark.parametrize("status", [408, 504])
def test_complete_provider_timeout_status_raises_timeout_error_without_retry(
    make_llm, status
):
    provider = _Provider(_status(status))

    with pytest.raises(
        LlmTimeoutError, match=rf"^The LLM provider timed out \(HTTP {status}\)$"
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 1


# --- REQ-006: other provider failures -------------------------------------


@pytest.mark.parametrize("status", [400, 403, 404, 413, 422, 500, 301])
def test_complete_other_non_2xx_raises_provider_error_without_retry(
    make_llm, clock, status
):
    provider = _Provider(_status(status))

    with pytest.raises(
        LlmProviderError, match=rf"^The LLM provider returned HTTP {status}$"
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("status", [502, 503])
def test_complete_bad_gateway_or_unavailable_is_retried_then_raises(
    make_llm, clock, status
):
    provider = _Provider(_status(status))

    with pytest.raises(
        LlmProviderError, match=rf"^The LLM provider returned HTTP {status}$"
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 3
    assert clock.sleeps == [0.5, 1.0]


@pytest.mark.parametrize("status", [401, 402])
def test_complete_rejected_key_or_account_raises_configuration_error(make_llm, status):
    provider = _Provider(_status(status))

    with pytest.raises(
        LlmConfigurationError,
        match=(
            r"^The LLM provider rejected the configured key or account "
            rf"\(HTTP {status}\)$"
        ),
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 1


# --- transport failures ----------------------------------------------------


def test_complete_connect_error_then_200_succeeds(make_llm, clock):
    provider = _Provider(httpx.ConnectError, _ok())

    assert _complete(make_llm(provider)).text == "hi"
    assert len(provider.requests) == 2
    assert clock.sleeps == [0.5]


def test_complete_connect_error_every_attempt_raises_provider_error(make_llm):
    provider = _Provider(httpx.ConnectError)

    with pytest.raises(
        LlmProviderError, match=r"^The LLM provider could not be reached$"
    ) as raised:
        _complete(make_llm(provider))

    assert len(provider.requests) == 3
    assert isinstance(raised.value.__cause__, httpx.ConnectError)


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(httpx.RemoteProtocolError, id="remote-protocol"),
        pytest.param(httpx.ReadError, id="read"),
    ],
)
def test_complete_other_transport_error_raises_provider_error_without_retry(
    make_llm, exception
):
    provider = _Provider(exception)

    with pytest.raises(
        LlmProviderError, match=r"^The LLM provider could not be reached$"
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 1


# --- a 2xx that is not a usable completion ---------------------------------


@pytest.mark.parametrize(
    ("code", "error", "pattern"),
    [
        pytest.param(429, LlmRateLimitError, r"HTTP 429", id="429"),
        pytest.param(
            502,
            LlmProviderError,
            r"^The LLM provider returned error code 502$",
            id="502",
        ),
        pytest.param(
            0, LlmProviderError, r"^The LLM provider returned error code 0$", id="zero"
        ),
        pytest.param(
            200,
            LlmProviderError,
            r"^The LLM provider returned error code 200$",
            id="200",
        ),
        pytest.param(
            1001,
            LlmProviderError,
            r"^The LLM provider returned error code 1001$",
            id="non-http",
        ),
        pytest.param(401, LlmConfigurationError, r"\(HTTP 401\)", id="401"),
        pytest.param(504, LlmTimeoutError, r"timed out \(HTTP 504\)", id="504"),
        pytest.param("oops", LlmProviderError, r"returned an error", id="non-int"),
        pytest.param(True, LlmProviderError, r"returned an error", id="bool"),
    ],
)
def test_complete_error_inside_a_200_is_mapped_and_not_retried(
    make_llm, clock, code, error, pattern
):
    body = {"error": {"code": code, "message": PROVIDER_ERROR_TEXT}}
    provider = _Provider(httpx.Response(200, json=body))

    with pytest.raises(error, match=pattern):
        _complete(make_llm(provider))

    assert len(provider.requests) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(httpx.Response(200, content=b"<html>"), id="not-json"),
        pytest.param(httpx.Response(200, content=b"\xc3\x28"), id="not-utf8"),
        pytest.param(httpx.Response(200, json=[1, 2]), id="json-list"),
        pytest.param(_ok(choices=None), id="null-choices"),
        pytest.param(_ok(choices=[]), id="empty-choices"),
        pytest.param(_ok(choices=["x"]), id="choice-not-object"),
        pytest.param(_ok(choices=[{"index": 0}]), id="no-message"),
        pytest.param(
            _ok(choices=[{"message": {"role": "assistant", "content": None}}]),
            id="null-content",
        ),
        pytest.param(_ok(usage=None), id="null-usage"),
        pytest.param(_ok(usage={"prompt_tokens": 3}), id="usage-missing-count"),
        pytest.param(
            _ok(usage={"prompt_tokens": -1, "completion_tokens": 1}),
            id="negative-usage",
        ),
        pytest.param(
            _ok(usage={"prompt_tokens": 3.0, "completion_tokens": 1}),
            id="float-usage",
        ),
        pytest.param(
            _ok(usage={"prompt_tokens": True, "completion_tokens": 1}),
            id="bool-usage",
        ),
    ],
)
def test_complete_2xx_that_is_not_a_completion_raises_provider_error(make_llm, reply):
    provider = _Provider(reply)

    with pytest.raises(
        LlmProviderError,
        match=r"^The LLM provider returned a response that is not a chat completion$",
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 1


@pytest.mark.parametrize("key", ["usage", "choices"])
def test_complete_missing_required_field_raises_provider_error(make_llm, key):
    with pytest.raises(LlmProviderError, match=r"is not a chat completion"):
        _complete(make_llm(_Provider(_without(key))))


def test_complete_body_over_the_size_cap_raises_provider_error(make_llm):
    def _huge_body() -> Iterator[bytes]:
        chunk = b" " * 65_536
        for _ in range(MAX_RESPONSE_BYTES // len(chunk) + 1):
            yield chunk

    provider = _Provider(httpx.Response(200, content=_huge_body()))

    with pytest.raises(
        LlmProviderError,
        match=rf"^The LLM provider's response exceeded {MAX_RESPONSE_BYTES} bytes$",
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 1


def test_complete_body_exactly_at_the_size_cap_is_read(make_llm):
    payload = json.dumps(_completion_body()).encode()
    padded = payload + b" " * (MAX_RESPONSE_BYTES - len(payload))

    completion = _complete(make_llm(_Provider(httpx.Response(200, content=padded))))

    assert completion.text == "hi"


def test_complete_2xx_body_that_fails_to_decode_raises_provider_error(make_llm, clock):
    reply = httpx.Response(
        # An iterator, so the response stays a stream until the adapter reads it.
        200,
        content=iter([b"not gzip at all"]),
        headers={"Content-Encoding": "gzip"},
    )
    provider = _Provider(reply)

    with pytest.raises(
        LlmProviderError, match=r"^The LLM provider's response could not be read$"
    ) as raised:
        _complete(make_llm(provider))

    assert len(provider.requests) == 1
    assert clock.sleeps == []
    assert isinstance(raised.value.__cause__, httpx.DecodingError)


def test_complete_2xx_body_nested_too_deep_raises_provider_error(make_llm):
    depth = 200_000
    nested = b"[" * depth + b"]" * depth
    assert len(nested) <= MAX_RESPONSE_BYTES
    provider = _Provider(httpx.Response(200, content=nested))

    with pytest.raises(
        LlmProviderError,
        match=r"^The LLM provider returned a response that is not a chat completion$",
    ):
        _complete(make_llm(provider))

    assert len(provider.requests) == 1


# --- client-safe messages --------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_status(400), id="400"),
        pytest.param(_status(401), id="401"),
        pytest.param(_status(429), id="429"),
        pytest.param(_status(504), id="504"),
        pytest.param(
            httpx.Response(
                200, json={"error": {"code": 502, "message": PROVIDER_ERROR_TEXT}}
            ),
            id="error-in-200",
        ),
        pytest.param(httpx.ConnectError, id="connect-error"),
        pytest.param(httpx.ReadTimeout, id="read-timeout"),
    ],
)
def test_complete_error_message_never_carries_the_key_or_provider_text(make_llm, reply):
    with pytest.raises(LlmError) as raised:
        _complete(make_llm(_Provider(reply)))

    _assert_never_carries(raised.value, API_KEY, PROVIDER_ERROR_TEXT, "hello")
