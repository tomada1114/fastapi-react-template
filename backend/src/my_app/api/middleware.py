"""Pure ASGI request identity and access records, including error responses."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import TYPE_CHECKING

from my_app.logging_config import request_id_var

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_PATTERN = re.compile(rb"[A-Za-z0-9._-]{1,128}")
logger = logging.getLogger("my_app.access")


class RequestIdMiddleware:
    """Keep identity active until even the outer error handler has responded."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the complete HTTP stack, preserving other ASGI scopes."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Echo the first valid id and emit exactly one access record."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = next(
            (
                value
                for name, value in scope["headers"]
                if name.lower() == b"x-request-id"
            ),
            b"",
        )
        request_id = (
            supplied.decode("ascii")
            if REQUEST_ID_PATTERN.fullmatch(supplied)
            else str(uuid.uuid7())
        )
        scope.setdefault("state", {})["request_id"] = request_id
        # ASGI paths are decoded: keep control characters and Unicode line
        # separators from creating additional physical text-log lines.
        path = json.dumps(scope["path"], ensure_ascii=True)[1:-1]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                message = {
                    **message,
                    "headers": [
                        *headers,
                        (b"x-request-id", request_id.encode("ascii")),
                    ],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            try:
                logger.info(
                    "%s %s %s %.1fms",
                    scope["method"],
                    path,
                    status,
                    duration_ms,
                    extra={
                        "method": scope["method"],
                        "path": path,
                        "status": status,
                        "duration_ms": duration_ms,
                        "request_id": request_id,
                    },
                )
            finally:
                request_id_var.reset(token)
