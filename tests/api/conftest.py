"""Fixtures for driving the FastAPI app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_app.api.app import create_app


@pytest.fixture
def client(make_container):
    """A client on an app built through the composition root.

    It gets an empty in-memory store and the fixed clock, so a response's
    ``created_at`` is known exactly.
    """
    with TestClient(create_app(container=make_container())) as test_client:
        yield test_client
