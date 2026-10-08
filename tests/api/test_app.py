from __future__ import annotations

from contextlib import ExitStack
from http import HTTPStatus
from importlib import metadata, reload
from typing import TYPE_CHECKING

import httpx2
import pytest
from fastapi.testclient import TestClient

import my_app
from my_app.api import app as app_module
from my_app.api.app import create_app
from my_app.composition import Container, build_llm
from my_app.core.errors import (
    AppError,
    LlmConfigurationError,
    LlmError,
    LlmProviderError,
    LlmRateLimitError,
    LlmTimeoutError,
)
from my_app.settings import Settings

if TYPE_CHECKING:
    from my_app.core.llm import LlmMessage

UNMAPPED_MESSAGE = "a rule with no status of its own"


class _UnmappedError(AppError):
    """A domain error ``create_app`` has no specific status for."""

    def __init__(self) -> None:
        super().__init__(UNMAPPED_MESSAGE)


def test_healthz_returns_ok(client):
    response = client.get("/healthz")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


def test_testclient_runs_on_httpx2_not_the_deprecated_httpx():
    assert issubclass(TestClient, httpx2.Client)


def test_openapi_uses_the_framework_default_version(make_container, monkeypatch):
    monkeypatch.setattr(metadata, "version", lambda _: "9.9.9")
    reload(my_app)
    reload(app_module)
    with TestClient(app_module.create_app(container=make_container())) as client:
        response = client.get("/openapi.json")

    assert response.json()["info"]["version"] == "0.1.0"


def test_unmapped_app_error_returns_400_not_500(make_container):
    app = create_app(container=make_container())

    @app.get("/unmapped")
    def _raise_unmapped() -> None:
        raise _UnmappedError

    with TestClient(app) as client:
        response = client.get("/unmapped")

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {"detail": UNMAPPED_MESSAGE}


@pytest.mark.parametrize(
    ("error", "status"),
    [
        pytest.param(
            LlmConfigurationError("LLM is not configured"),
            HTTPStatus.SERVICE_UNAVAILABLE,
            id="configuration-503",
        ),
        pytest.param(
            LlmRateLimitError("rate-limited"),
            HTTPStatus.TOO_MANY_REQUESTS,
            id="rate-limit-429",
        ),
        pytest.param(
            LlmTimeoutError("timed out"), HTTPStatus.GATEWAY_TIMEOUT, id="timeout-504"
        ),
        pytest.param(
            LlmProviderError("provider failed"),
            HTTPStatus.BAD_GATEWAY,
            id="provider-502",
        ),
        pytest.param(
            LlmError("unmapped llm failure"), HTTPStatus.BAD_GATEWAY, id="base-502"
        ),
    ],
)
def test_llm_error_returns_its_status_with_the_message(make_container, error, status):
    app = create_app(container=make_container())

    @app.get("/llm-error")
    def _raise_llm_error() -> None:
        raise error

    with TestClient(app) as client:
        response = client.get("/llm-error")

    assert response.status_code == status
    assert response.json() == {"detail": str(error)}


def test_llm_route_without_key_answers_503(make_container):
    app = create_app(container=make_container())

    @app.get("/llm")
    def _complete() -> str:
        llm = build_llm(Settings())
        messages: list[LlmMessage] = [{"role": "user", "content": "hi"}]
        return llm.complete(messages, max_tokens=16, timeout=5).text

    with TestClient(app) as client:
        response = client.get("/llm")

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json() == {
        "detail": "LLM is not configured: set OPENROUTER_API_KEY to enable it"
    }


def test_create_app_without_settings_reads_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_APP_DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")

    with TestClient(create_app()) as writer:
        created = writer.post("/todos", json={"title": "from env"})
    with TestClient(create_app()) as reader:
        titles = [todo["title"] for todo in reader.get("/todos").json()]

    assert created.status_code == HTTPStatus.CREATED
    assert titles == ["from env"]


def test_create_app_each_call_owns_an_independent_store():
    with TestClient(create_app(Settings())) as first:
        first.post("/todos", json={"title": "only in first"})

    with TestClient(create_app(Settings())) as second:
        assert second.get("/todos").json() == []


def test_create_app_with_sqlite_keeps_todos_across_apps(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'todos.db'}")
    with TestClient(create_app(settings)) as first:
        first.post("/todos", json={"title": "survives"})

    with TestClient(create_app(settings)) as second:
        titles = [todo["title"] for todo in second.get("/todos").json()]

    assert titles == ["survives"]


def test_create_app_shutdown_closes_factory_built_container(
    monkeypatch, make_container
):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "built")
    container = Container(make_container().todos, _resources=resources)
    monkeypatch.setattr(app_module, "build_container", lambda _: container)

    app = create_app(Settings())
    assert closed == []
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == HTTPStatus.OK
        assert closed == []

    assert closed == ["built"]


def test_create_app_shutdown_leaves_supplied_container_caller_owned(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "supplied")
    container = Container(make_container().todos, _resources=resources)

    with TestClient(create_app(container=container)) as client:
        assert client.get("/healthz").status_code == HTTPStatus.OK

    assert closed == []
    container.close()
    assert closed == ["supplied"]
