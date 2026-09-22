"""Logging setup and the per-request context middleware.

``configure_logging`` decides, once at startup, which log records are
written and what each line looks like. ``request_context_middleware`` gives
every request an ID, returns it in the ``X-Request-ID`` header, and writes
one ``key=value`` log line per request with the method, path, status, and
duration (plan §12, Observability). The same ID appears in error bodies and
in the log, so a failed request a user reports can be found in the logs.
"""

# Standard logging; creates this module's logger and configures output.
import logging

# High-resolution clock used to measure how long each request takes.
import time

# Generates new request IDs and validates the ones clients send.
import uuid

# Type of call_next: a function whose result is awaited.
from collections.abc import Awaitable

# Type of call_next: something that can be called like a function.
from collections.abc import Callable

# Per-request variable, so concurrent requests never see each other's ID.
from contextvars import ContextVar

# The incoming request; the middleware reads headers and stores the ID on its state.
from fastapi import Request

# The outgoing response; the middleware adds the X-Request-ID header to it.
from fastapi import Response

logger = logging.getLogger(__name__)

# Holds the current request's ID for code that has no access to the request,
# such as services and log helpers. Each concurrent request sees its own value.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def _resolve_request_id(header_value: str | None) -> str:
    """Choose the ID for a request, reusing the client's only if it is a UUID.

    Reusing an ID that a proxy or the web app already created lets one ID
    follow a request across systems. Anything else is replaced, because the
    value is written to the logs: a header containing a line break could
    forge a fake log line, and a huge one would bloat every entry. Valid
    UUIDs are normalized, so every spelling of the same ID (uppercase,
    braces, no dashes, a ``urn:uuid:`` prefix) is logged and returned in one
    searchable form.

    Args:
        header_value: The incoming ``X-Request-ID`` header, or ``None`` when
            the client didn't send one.

    Returns:
        The request ID as a lowercase, 36-character UUID string.

    Example:
        ``_resolve_request_id("{3F2C8A1E-9B4D-4C6E-8F00-123456789ABC}")``
        returns ``"3f2c8a1e-9b4d-4c6e-8f00-123456789abc"``.
    """
    if header_value is None:
        return str(uuid.uuid4())

    try:
        parsed = uuid.UUID(header_value)
    except ValueError:
        return str(uuid.uuid4())

    return str(parsed)


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Attach a request ID to each request, and log one line when it finishes.

    The ID is stored in two places: ``request.state``, where the error
    handlers read it, and ``request_id_var``, for code that doesn't receive
    the request. The log line contains the path but never the query string,
    because query parameters can carry patient names or phone numbers.
    ``user_id`` is ``None`` until authentication exists (Milestone 1.2).

    The context variable is reset in ``finally``, so one request's ID never
    leaks into later work. When the route raises an unexpected exception,
    this middleware writes no line and adds no header: the 500 handler runs
    outside it, logs the traceback with the same request ID, and puts the ID
    in the response body.

    Args:
        request: The incoming request.
        call_next: Runs the rest of the application and returns its response.

    Returns:
        The application's response, with the ``X-Request-ID`` header added.

    Example:
        ``app.middleware("http")(request_context_middleware)``
    """
    request_id: str = _resolve_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    token = request_id_var.set(request_id)

    start = time.perf_counter()

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            "request_id=%s user_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            None,
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
    finally:
        request_id_var.reset(token)

    return response


def configure_logging(level: str) -> None:
    """Configure how every log record in the application is written.

    Without this, Python's fallback prints only warnings and errors, so the
    per-request INFO lines would silently disappear. Each line gets a
    timestamp, level, and logger name in front of the message. ``force=True``
    replaces any earlier configuration, so calling this again, for example
    in tests, never adds a second handler that would print every line twice.

    Args:
        level: Minimum level to write, such as ``"INFO"``; normally
            ``Settings.log_level``.

    Example:
        ``configure_logging(get_settings().log_level)``
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
