from __future__ import annotations

import typer
from typer.core import TyperCommand

from my_app.cli.context import get_container


def test_get_container_sibling_contexts_share_invocation_services():
    root = typer.Context(TyperCommand("root"))
    first = typer.Context(TyperCommand("first"), parent=root)
    second = typer.Context(TyperCommand("second"), parent=root)

    container = get_container(first)
    container.todos.create("buy milk")
    shared = get_container(second)

    assert shared is container
    assert shared.todos.list_todos()[0].title == "buy milk"
    assert root.obj is container


def test_get_container_supplied_ancestor_services_ignore_invalid_settings(
    make_container, monkeypatch
):
    monkeypatch.setenv("MY_APP_DATABASE_URL", "postgresql://x")
    container = make_container()
    root = typer.Context(TyperCommand("root"), obj=container)
    child = typer.Context(TyperCommand("child"), parent=root)

    result = get_container(child)

    assert result is container


def test_get_container_supplied_child_services_override_ancestor(make_container):
    ancestor = make_container()
    supplied = make_container()
    root = typer.Context(TyperCommand("root"), obj=ancestor)
    child = typer.Context(TyperCommand("child"), parent=root, obj=supplied)

    result = get_container(child)

    assert result is supplied
    assert root.obj is ancestor
