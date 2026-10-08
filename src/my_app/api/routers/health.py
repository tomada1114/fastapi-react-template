"""Liveness probe for load balancers and container orchestrators."""

from __future__ import annotations

from fastapi import APIRouter

from my_app.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> HealthResponse:
    """Report that the process is serving requests.

    It touches no repository on purpose: a slow or missing database must not
    get a live process restarted.
    """
    return HealthResponse()
