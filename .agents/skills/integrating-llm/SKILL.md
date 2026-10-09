---
name: integrating-llm
description: >
  Covers the optional LLM layer: LlmPort and its value types in src/my_app/core/llm.py,
  the LlmError family, the fake, closed, and OpenRouter adapters, composition.build_llm,
  OPENROUTER_API_KEY and MY_APP_LLM_MODEL, the ai extra, retries and the request
  deadline, and the shared LLM contract suite. Use when calling a model from a service,
  wiring an LLM-backed route, testing code that uses the LLM, changing the OpenRouter
  adapter, adding a provider, or removing the layer.
---

# Integrating an LLM

**Owns:** the LLM layer — its port, value types, error family, adapters, `build_llm`,
its two settings, the `ai` extra's purpose, the retry and deadline rules, and how code
that calls a model is tested. **Does not own:** which HTTP status an `LlmError` becomes
(`designing-errors`); whether a package may be added or an extra changed
(`managing-dependencies`); the shape of a route that calls a service
(`building-api-routes`); ports, adapters, and settings in general
(`designing-core-logic`).

## The layer at a glance

| File | Holds |
|---|---|
| `src/my_app/core/llm.py` | `LlmMessage`, `LlmUsage`, `LlmCompletion`, `DEFAULT_LLM_TIMEOUT_SECONDS`, `check_completion_request` |
| `src/my_app/core/ports.py` | `LlmPort`, its contract in the docstrings |
| `src/my_app/core/errors.py` | `LlmError` and its four subclasses |
| `src/my_app/adapters/fake_llm.py` | `FakeLlm`, the fake for tests, recording `FakeLlmCall`s |
| `src/my_app/adapters/closed_llm.py` | `ClosedLlm`, what an app without a key gets |
| `src/my_app/adapters/openrouter.py` | `OpenRouterLlm`, the only module importing `httpx` |
| `src/my_app/composition.py` | `build_llm(settings)` |
| `tests/adapters/test_llm_contract.py` | the one contract suite every completing adapter runs |

The core stays HTTP-free (`designing-core-logic`'s "The direction dependencies
point"); only an adapter speaks to a provider.

## The port's contract

`complete(messages, *, model=None, max_tokens, timeout) -> LlmCompletion`.

- **Arguments are checked before any request.** Every adapter calls
  `check_completion_request` first, so a bad argument is a `ValueError` whichever
  adapter is wired in. Arguments come from code, so that is a bug and keeps its
  traceback. A service that forwards user input validates it first, with its own
  domain error (`designing-errors`' "Two kinds of failure").
- **`model=None`** means the model the adapter was built with (`MY_APP_LLM_MODEL`).
- **`timeout` is the call's budget**, in seconds, shared by every attempt and every
  wait between them. It is enforced between steps, not as a hard cutoff: see the
  known limit under "Retries and the deadline". Pass `DEFAULT_LLM_TIMEOUT_SECONDS`
  (60) without a reason to pick another.
- **What a caller does about each error:**

| Error | Means | The caller |
|---|---|---|
| `LlmConfigurationError` | no key, the `ai` extra missing, or a key or account the provider rejected | reports it; an operator must act |
| `LlmRateLimitError` | rate limiting outlasted the retries | tells the user to try later |
| `LlmTimeoutError` | the deadline passed, or the provider timed out | may retry with a new budget |
| `LlmProviderError` | the provider failed, was unreachable, or did not answer a completion | reports it |

Every message is client-safe: never the key, a prompt, a model's output, or the
provider's own error text, which can echo the prompt.

## Configuration, closed by default

- **`OPENROUTER_API_KEY`**, unprefixed — the name OpenRouter's documentation and the
  sibling templates use; `Settings.openrouter_api_key` reads it through a
  `validation_alias`, and `MY_APP_OPENROUTER_API_KEY` is not read. Unset or blank,
  `build_llm` returns `ClosedLlm`, and neither the OpenRouter adapter nor `httpx` is
  imported. A key exported for another tool in the same shell opens the layer too:
  unset it where the app runs if that is not meant.
- **`MY_APP_LLM_MODEL`**, defaulting to `settings.DEFAULT_LLM_MODEL`,
  `deepseek/deepseek-v4.1-flash` (listed in https://openrouter.ai/api/v1/models,
  checked 2026-10-06). OpenRouter's catalogue is the authority on model ids, so the
  setting is not validated further; a model it does not know fails as a provider 400.
- **The `ai` extra** carries `httpx`: `uv sync --extra ai` in a checkout, or
  `pip install 'my-app[ai]'`. A key set without it makes `build_llm` raise
  `LlmConfigurationError` naming the extra. The `dev` group also has `httpx`, so the
  tests and mypy see it without the extra.

A route on `ClosedLlm` answers 503, so no billed endpoint opens by accident.

## Calling it from a service

A service that needs a model takes `llm: LlmPort` in its constructor, and
`build_container` passes `build_llm(settings)` and stores the service in a new
`Container` field (`designing-core-logic`'s "The composition root wires everything
once"). For example, a summarizing service's constructor would take
`llm: LlmPort` and call `self._llm.complete([...], max_tokens=256,
timeout=DEFAULT_LLM_TIMEOUT_SECONDS)`.

- With `OPENROUTER_API_KEY` set but the `ai` extra missing, `build_llm` raises
  `LlmConfigurationError` when the container is built — at app startup,
  outside the request error mapping — so it surfaces as a startup failure
  with that message. That is intended (fail fast); install the extra or unset the key.

- Routes stay synchronous; a call can hold one of FastAPI's thread-pool slots for up
  to its `timeout`.
- A route that bills is the app's to protect: access control and rate limiting are
  not shipped. The sibling nextjs-app-template's issue tomada1114/nextjs-app-template#115 is the pattern to adapt.
- The route declares the statuses its errors become in `responses=`
  (`building-api-routes`).

## Retries and the deadline

`OpenRouterLlm` sends at most `DEFAULT_MAX_RETRIES` (2) retries:

- **Retried:** HTTP 429, 502, and 503, and `httpx.ConnectError` (nothing reached the
  provider). The wait is `Retry-After` in delta-seconds on a 429 or 503, else
  `BASE_BACKOFF_SECONDS * 2**n` capped at `MAX_BACKOFF_SECONDS` — 0.5 s, then 1.0 s.
  No jitter: two retries per call make no herd, and exact waits keep tests exact.
- **A `Retry-After` above `MAX_RETRY_AFTER_SECONDS` (8 s) ends the call at once.**
  Retrying sooner than the provider asked would only be refused again.
- **Never retried:** an error inside a 2xx body; any `httpx` timeout, a
  `ConnectTimeout` included (it becomes `LlmTimeoutError`), while an
  `httpx.ConnectError` is retried; and any other transport error. The request was
  accepted, or may have been, and a retry could bill twice.
- **The deadline wins.** A retry happens only while its wait ends before the
  deadline; otherwise the last mapped error is raised. Each attempt's `httpx`
  timeout is the budget left.
- **Known limit — `timeout` is not a hard wall-clock cutoff.** `httpx` has no
  whole-request timeout: each network phase (connect, TLS, each write, each socket
  read, the headers included) is bounded separately by the budget left when the
  attempt began. The deadline is checked between attempts, once the headers arrive,
  and after each body chunk. Ordinary phases can add up to several times `timeout`,
  and a server that trickles bytes can hold the call indefinitely. A caller that
  needs a hard cutoff runs the call under its own cancellation.

The status meanings, the `{"error": {"code", "message", "metadata"}}` envelope, errors
inside a 200, and `Retry-After` on 429 and 503 are OpenRouter's
(https://openrouter.ai/docs/api-reference/errors, checked 2026-10-06); the endpoint,
the request fields, the response shape, and that `usage` is always returned are in
https://openrouter.ai/docs/api-reference/chat-completion (checked 2026-10-06).

## Testing fake-first

- **Core and service tests use `FakeLlm`**: `FakeLlm(reply="hi")` answers every call,
  `FakeLlm(error=LlmRateLimitError("..."))` drives an error path, and `.calls`
  records each request with its resolved model. It runs the same argument check as a
  real adapter.
- **A route test** builds the app with a container whose service holds a `FakeLlm`
  and asserts the status and exact body (`building-api-routes`).
- **An adapter test** serves the provider from `httpx.MockTransport` and injects
  `sleep` and `monotonic`, as `tests/adapters/test_openrouter.py` does: no network,
  no real waiting.
- **No live call in the suite.** It would bill, flake, and need a key in CI, and a
  skipped test is a weakened gate (AGENTS.md's "Security and human approval"). The
  owner checks a live key by hand:

```bash
OPENROUTER_API_KEY=... uv run --locked --extra ai python -c "from my_app.composition import build_llm; from my_app.settings import Settings; print(build_llm(Settings()).complete([{'role': 'user', 'content': 'Say hi'}], max_tokens=16, timeout=30))"
```

`tests/test_composition.py` pins the closed default: a fresh interpreter imports the
app, builds it with no key, and finds neither `httpx` nor the OpenRouter adapter
loaded; another hides `httpx`, builds the app, and drives the to-do service through
`build_container`, with `ClosedLlm` as the model.

## Adding a provider

1. A new adapter module in `adapters/` that satisfies `LlmPort`, calls
   `check_completion_request` first and sends the message tuple it returns, and maps
   its failures onto the four errors.
2. A `pytest.param` in `LLM_FACTORIES` in `tests/adapters/test_llm_contract.py`, and
   `tests/adapters/test_<adapter>.py` for what only it does.
3. A `Settings` field that chooses between providers, read in `build_llm`; a new
   package goes through `managing-dependencies` first.

## Removing the layer

Delete `core/llm.py`, `LlmPort` from `core/ports.py`, the `Llm*Error` classes and their
cases in `_status_for` (`api/app.py`), `adapters/fake_llm.py`, `adapters/closed_llm.py`,
`adapters/openrouter.py`, `build_llm`, the two settings with their
`_isolate_settings_env` lines in `tests/conftest.py`, and the LLM tests
(`tests/core/test_llm.py`, the `tests/adapters/test_*llm*.py` and `test_openrouter.py`
files, and the LLM cases in `tests/core/test_errors.py`, `tests/test_settings.py`,
`tests/test_composition.py`, and `tests/api/test_app.py`). Remove the `ai` extra and
run `uv lock`. Then drop the LLM text elsewhere:

- the docstrings of `core/__init__.py`, `adapters/__init__.py`, `settings.py`, and
  `_status_for`;
- `designing-errors`: the LLM statuses in its description, the `Llm*Error` rows of its
  tables, and its `LlmError` and `LlmConfigurationError` prose;
- `managing-dependencies`' bullet on the `ai` extra, and `designing-core-logic`'s
  note on the unprefixed `OPENROUTER_API_KEY`;
- AGENTS.md's Architecture tree lines for the LLM modules and the key;
- the README's LLM rows and sentences, its Architecture line included, and the
  project's ADR for the layer, if it has one.

<!-- template-only -->
In the template, also drop `TEMPLATE.md`'s "Why an optional LLM layer behind a port?"
and the `ai` extra from its runtime-dependencies sentence.
<!-- /template-only -->

Then delete this skill and its row in AGENTS.md's Skills table, and run
`just agents-sync` and `just verify`. A project that keeps the layer records it as its
own ADR (`recording-architecture-decisions`).
