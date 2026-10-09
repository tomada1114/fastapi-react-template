"""The FastAPI application factory and its domain-error mapping."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from my_app.api.routers import health, todos
from my_app.api.schemas import (
    PROBLEM_MEDIA_TYPE,
    ProblemDetails,
    ProblemFieldError,
    problem_responses,
    status_phrase,
)
from my_app.composition import Container, build_container
from my_app.core.errors import (
    AppError,
    InvalidCursorError,
    InvalidPageLimitError,
    InvalidTodoError,
    TodoNotFoundError,
)
from my_app.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from fastapi.routing import APIRoute
    from starlette.types import ASGIApp

APP_TITLE = "My App"
API_PREFIX = "/api"
logger = logging.getLogger("my_app.api.errors")


class _ApiApp(FastAPI):
    """Apply the API media types and keep CORS outside server-error handling."""

    cors_origins: tuple[str, ...] = ()

    def build_middleware_stack(self) -> ASGIApp:
        """Build lazily so callers can still register middleware before startup."""
        middleware = super().build_middleware_stack()
        if self.cors_origins:
            middleware = CORSMiddleware(
                middleware,
                allow_origins=self.cors_origins,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                allow_headers=["Content-Type"],
                allow_credentials=False,
            )
        return middleware

    def openapi(self) -> dict[str, Any]:
        """Publish error models as Problem Details, preserving success media types.

        FastAPI registers ``responses=`` models under the route's success
        media type. Keep that schema registration, then correct error content
        in its cached OpenAPI document. ``Any`` is the framework's schema type.
        """
        schema = super().openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                if not isinstance(operation, dict) or "responses" not in operation:
                    continue
                for response in operation["responses"].values():
                    content = response.get("content", {})
                    if content.get("application/json", {}).get("schema") == {
                        "$ref": "#/components/schemas/ProblemDetails"
                    }:
                        content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
        return schema


def route_operation_id(route: APIRoute) -> str:
    """Keep a route function name stable as its generated client name."""
    return route.name


def create_app(
    settings: Settings | None = None, *, container: Container | None = None
) -> FastAPI:
    """Build an application with its own services and storage.

    A factory rather than a module-level ``app`` so each test gets a fresh
    store, and so ``uvicorn --factory`` reads the environment only when the
    server starts.

    Args:
        settings: Configuration to build services from; read from the
            environment when omitted. Storage configuration is ignored when
            ``container`` is given; HTTP settings still apply.
        container: Services already built by the composition root. Tests pass
            one built with a fixed clock; production code leaves it out. The
            caller owns a supplied container; lifespan shutdown awaits
            ``aclose()`` only on a container this factory builds.

    Returns:
        The application, ready for uvicorn or ``TestClient``.
    """
    if settings is None:
        # A supplied container already owns storage; only HTTP settings apply.
        settings = Settings(database_url=None) if container is not None else Settings()
    owns_container = container is None
    if container is None:
        container = build_container(settings)
    services = container

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owns_container:
                await services.aclose()

    app = _ApiApp(
        title=APP_TITLE,
        lifespan=lifespan,
        generate_unique_id_function=route_operation_id,
        responses=problem_responses(400, 422, 500),
    )
    app.cors_origins = tuple(settings.cors_origins)
    app.state.container = services
    app.include_router(health.router)
    app.include_router(todos.router, prefix=API_PREFIX)
    # The decorator form, unlike add_exception_handler, type-checks a handler
    # that takes AppError rather than any Exception.
    app.exception_handler(AppError)(_handle_app_error)
    app.exception_handler(RequestValidationError)(_handle_validation_error)
    app.exception_handler(HTTPException)(_handle_http_error)
    app.exception_handler(Exception)(_handle_unexpected_error)
    return app


def _status_for(error: AppError) -> HTTPStatus:
    """Choose the HTTP status a domain error becomes.

    The one place the mapping lives. Any ``AppError`` without a case here is
    still the client's problem, not the server's, so a new subclass is a 400
    until it gets its own case — never an unhandled 500.

    Args:
        error: The domain error a service raised.

    Returns:
        The status to answer with.
    """
    match error:
        case TodoNotFoundError():
            status = HTTPStatus.NOT_FOUND
        case InvalidTodoError() | InvalidCursorError() | InvalidPageLimitError():
            status = HTTPStatus.UNPROCESSABLE_CONTENT
        case _:
            status = HTTPStatus.BAD_REQUEST
    return status


def _problem_response(
    status: int,
    detail: str,
    code: str,
    *,
    errors: list[ProblemFieldError] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Serialize a client-safe error, omitting absent extensions."""
    body = ProblemDetails(
        title=status_phrase(status),
        status=status,
        detail=detail,
        code=code,
        errors=errors,
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(exclude_none=True),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


async def _handle_app_error(_: Request, error: AppError) -> JSONResponse:
    """Translate the domain status table and code into Problem Details."""
    return _problem_response(_status_for(error), str(error), error.code)


async def _handle_validation_error(
    _: Request, error: RequestValidationError
) -> JSONResponse:
    """Expose field locations and messages without echoing inputs or context."""
    errors = [
        ProblemFieldError(loc=list(item["loc"]), message=item["msg"], type=item["type"])
        for item in error.errors()
    ]
    return _problem_response(
        422, "Request validation failed", "request_invalid", errors=errors
    )


async def _handle_http_error(_: Request, error: HTTPException) -> Response:
    """Keep protocol headers and leave statuses that forbid a body empty."""
    if not is_body_allowed_for_status_code(error.status_code):
        return Response(status_code=error.status_code, headers=error.headers)
    code = {404: "not_found", 405: "method_not_allowed"}.get(
        error.status_code, "http_error"
    )
    detail = (
        error.detail
        if isinstance(error.detail, str)
        else status_phrase(error.status_code)
    )
    return _problem_response(error.status_code, detail, code, headers=error.headers)


async def _handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
    """Keep exception details in the traceback log, never in the client body."""
    logger.error("Unhandled exception", exc_info=error)
    return _problem_response(500, "An unexpected error occurred", "internal_error")
