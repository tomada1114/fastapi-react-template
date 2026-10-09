from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from contextlib import ExitStack, suppress
from datetime import UTC
from pathlib import Path

import pytest
from pydantic import SecretStr

from my_app import composition
from my_app.adapters.closed_llm import ClosedLlm
from my_app.adapters.memory import InMemoryTodoRepository
from my_app.adapters.openrouter import OpenRouterLlm
from my_app.composition import Container, build_container, build_llm, utc_now
from my_app.core.errors import LlmConfigurationError
from my_app.settings import OPENROUTER_API_KEY_ENV, Settings
from tests.settings_env import without_settings_env

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
_LLM_MODULES = '("httpx", "my_app.adapters.openrouter")'
# Run in a fresh interpreter: this test process has long since imported httpx.
# The first probe is an install with the `ai` extra and no key; the second
# hides httpx, as an install without the extra has none.
_PROBE_WITH_EXTRA = (
    "import sys\n"
    "from my_app.api.app import create_app\n"
    "from my_app.composition import build_llm\n"
    "from my_app.settings import Settings\n"
    "create_app(Settings())\n"
    "build_llm(Settings())\n"
    f"print(sorted(m for m in {_LLM_MODULES} if m in sys.modules))\n"
)
_PROBE_WITHOUT_EXTRA = (
    "import sys\n"
    "sys.modules['httpx'] = None\n"
    "from my_app.api.app import create_app\n"
    "from my_app.composition import build_container, build_llm\n"
    "from my_app.settings import Settings\n"
    "create_app(Settings())\n"
    "llm = build_llm(Settings())\n"
    "with build_container(Settings()) as container:\n"
    "    container.todos.create('x')\n"
    "    count = len(container.todos.list_todos())\n"
    "print(type(llm).__name__, count)\n"
)


def test_build_container_default_settings_uses_an_independent_memory_store(
    make_container,
):
    first = make_container()
    second = make_container()

    first.todos.create("only in first")

    assert second.todos.list_todos() == []


def test_build_container_sqlite_settings_shares_the_file(make_container, tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'todos.db'}")
    created = make_container(settings).todos.create("buy milk")

    reopened = make_container(settings)

    assert reopened.todos.list_todos() == [created]


def test_build_container_injected_clock_stamps_created_at(make_container, fixed_now):
    todo = make_container().todos.create("buy milk")

    assert todo.created_at == fixed_now


def test_utc_now_returns_timezone_aware_utc_time():
    assert utc_now().tzinfo is UTC


def test_build_llm_without_key_returns_closed_llm():
    assert isinstance(build_llm(Settings()), ClosedLlm)


def test_build_llm_with_key_returns_openrouter_with_the_configured_model():
    settings = Settings(
        openrouter_api_key=SecretStr("test-key"), llm_model="test/model"
    )

    llm = build_llm(settings)

    assert isinstance(llm, OpenRouterLlm)
    assert llm.model == "test/model"


def test_build_llm_with_key_and_default_model_uses_the_default(monkeypatch):
    monkeypatch.setenv(OPENROUTER_API_KEY_ENV, "test-key")

    llm = build_llm(Settings())

    assert isinstance(llm, OpenRouterLlm)
    assert llm.model == "deepseek/deepseek-v4.1-flash"


def test_build_llm_with_key_but_without_httpx_raises_configuration_error(
    monkeypatch,
):
    monkeypatch.setitem(sys.modules, "httpx", None)
    monkeypatch.delitem(sys.modules, "my_app.adapters.openrouter", raising=False)

    with pytest.raises(
        LlmConfigurationError,
        match=r"httpx is not installed: install the 'ai' extra \(uv sync --extra ai\)",
    ):
        build_llm(Settings(openrouter_api_key=SecretStr("test-key")))


def test_build_llm_import_error_other_than_httpx_propagates(monkeypatch):
    monkeypatch.setitem(sys.modules, "my_app.adapters.openrouter", None)

    with pytest.raises(ModuleNotFoundError, match=r"my_app\.adapters\.openrouter"):
        build_llm(Settings(openrouter_api_key=SecretStr("test-key")))


def _run_probe(probe: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv: this interpreter and a literal
        [sys.executable, "-c", probe],
        env=without_settings_env(os.environ),
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def test_app_with_extra_and_no_key_loads_no_llm_code():
    assert _run_probe(_PROBE_WITH_EXTRA) == "[]"


def test_app_without_extra_imports_and_runs_with_the_llm_closed():
    assert _run_probe(_PROBE_WITHOUT_EXTRA) == "ClosedLlm 1"


def test_pyproject_httpx_is_only_in_the_ai_extra():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    runtime = [dep for dep in project["dependencies"] if dep.startswith("httpx")]

    assert runtime == []
    assert "httpx>=0.28" in project["optional-dependencies"]["ai"]


def test_container_close_releases_registered_resource_once(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "resource")
    container = Container(make_container().todos, _resources=resources)

    container.close()
    container.close()

    assert closed == ["resource"]


def test_container_context_exit_releases_registered_resource(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "resource")
    container = Container(make_container().todos, _resources=resources)

    with container as entered:
        assert entered is container
        assert closed == []

    assert closed == ["resource"]


def test_container_context_failure_releases_registered_resource(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "resource")
    container = Container(make_container().todos, _resources=resources)

    message = "operation failed"
    with pytest.raises(ValueError, match="operation failed"), container:
        raise ValueError(message)

    assert closed == ["resource"]


def test_container_cleanup_failure_runs_remaining_callbacks_and_propagates(
    make_container,
):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "remaining")

    def fail_cleanup():
        message = "cleanup failed"
        raise ValueError(message)

    resources.callback(fail_cleanup)
    container = Container(make_container().todos, _resources=resources)

    with pytest.raises(ValueError, match="cleanup failed"):
        container.close()
    container.close()

    assert closed == ["remaining"]


def test_build_container_failure_closes_partially_registered_resources(monkeypatch):
    closed: list[str] = []

    def fail_build(settings, resources=None):
        if resources is not None:
            resources.callback(closed.append, "partial")
        message = "build failed"
        raise ValueError(message)

    monkeypatch.setattr(composition, "_build_repository", fail_build)

    with pytest.raises(ValueError, match="build failed"):
        build_container(Settings())

    assert closed == ["partial"]


def test_build_container_success_keeps_registered_resources_until_close(monkeypatch):
    closed: list[str] = []

    def build_repository(settings, resources):
        resources.callback(closed.append, "owned")
        return InMemoryTodoRepository()

    monkeypatch.setattr(composition, "_build_repository", build_repository)

    container = build_container(Settings())
    assert closed == []
    container.close()
    container.close()

    assert closed == ["owned"]


def test_container_context_failure_forwards_exception_details_to_resource(
    make_container,
):
    exits: list[tuple[object, object, object]] = []

    class RecordingResource:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            exits.append((exc_type, exc_value, traceback))
            return False

    resources = ExitStack()
    resources.enter_context(RecordingResource())
    container = Container(make_container().todos, _resources=resources)
    error = ValueError("operation failed")

    with pytest.raises(ValueError, match="operation failed"), container:
        raise error

    assert exits == [(ValueError, error, error.__traceback__)]
    container.close()
    assert len(exits) == 1


def test_container_context_failure_preserves_resource_suppression(make_container):
    closed: list[str] = []
    resources = ExitStack()
    resources.callback(closed.append, "remaining")
    resources.enter_context(suppress(ValueError))
    container = Container(make_container().todos, _resources=resources)
    message = "intentionally suppressed"

    with container:
        raise ValueError(message)

    container.close()
    assert closed == ["remaining"]
