"""Domain exceptions and the handlers that turn every error into one format.

Services raise the exceptions defined here instead of ``HTTPException``, so
business code never deals with HTTP. The handlers registered by
``register_exception_handlers`` convert those exceptions, FastAPI's input
validation errors, Starlette's routing errors, and unexpected crashes into
the standard error body from plan §11::

    {"error": {"code": ..., "message": ..., "details": [...], "request_id": ...}}

A client can therefore handle every failure the same way, and the
``request_id`` links a failed response to its log line.

Example:
    ``raise ConflictError("Not enough stock.", code=ErrorCode.INSUFFICIENT_STOCK)``
    becomes a 409 response with that code.
"""

# Standard logging; records the traceback of unexpected errors.
import logging

# Enum whose members are also strings; lists every allowed error code.
from enum import StrEnum

# Type of the values inside an error's details.
from typing import Any

# Application type that register_exception_handlers attaches the handlers to.
from fastapi import FastAPI

# The incoming request; handlers read the request ID from its state.
from fastapi import Request

# Raised by FastAPI when a request doesn't match the Pydantic schema.
from fastapi.exceptions import RequestValidationError

# Response with a JSON body and a status code; the shape of every error response.
from fastapi.responses import JSONResponse

# Starlette's HTTP error, raised for unknown routes, wrong methods, and security helpers.
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    """Every machine-readable error code the API can return.

    Clients branch on these codes, not on the human-readable message, so the
    codes are a public contract. Keeping them in one enum means a misspelled
    code fails when the module loads instead of silently reaching a client.
    Because ``StrEnum`` members are strings, they serialize to JSON as plain
    text such as ``"NOT_FOUND"``.

    Attributes:
        INTERNAL_ERROR: An unexpected server error (500).
        BAD_REQUEST: The request is well formed but can't be processed (400).
        AUTHENTICATION_FAILED: Missing, invalid, or expired credentials (401).
        PERMISSION_DENIED: The user's role lacks the required permission (403).
        NOT_FOUND: The resource doesn't exist or is outside the user's scope (404).
        CONFLICT: A business rule blocks the action (409).
        RATE_LIMITED: Too many attempts in a short time (429).
        VALIDATION_ERROR: The input doesn't match the request schema (422).
        METHOD_NOT_ALLOWED: The route exists but not for this HTTP method (405).
        PASSWORD_CHANGE_REQUIRED: A temporary password must be replaced first (403).
        INVALID_STATUS_TRANSITION: The record's current status forbids the action (409).
        APPOINTMENT_SLOT_TAKEN: The doctor or patient is already booked then (409).
        INSUFFICIENT_STOCK: Non-expired stock can't cover the quantity (409).
        ACTIVATION_FAILED: A portal activation code or MRN didn't match (400).
    """

    INTERNAL_ERROR = "INTERNAL_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    APPOINTMENT_SLOT_TAKEN = "APPOINTMENT_SLOT_TAKEN"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    ACTIVATION_FAILED = "ACTIVATION_FAILED"


class AppError(Exception):
    """Base class for every error a service raises on purpose.

    Each subclass fixes the HTTP status for one kind of failure, while each
    instance carries its own message, an optional more specific code, and
    optional details. One handler registered for ``AppError`` serves every
    subclass, because exception handlers match subclasses too. Raising
    ``AppError`` itself produces a 500, so services should always raise a
    subclass.

    Attributes:
        status_code: HTTP status returned for this class of error.
        code: Machine-readable code. The class default is used unless the
            caller passes a more specific one.
        message: Human-readable explanation, safe to show to the user.
        details: Extra structured information, such as which medicines are
            short. Always a list, empty when there is nothing to add.
    """

    status_code: int = 500
    code: str = ErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        """Create an error with a message and optional code and details.

        ``code`` and ``details`` are keyword-only, so a list can never be
        passed as a code by position. The instance stores its own ``code``
        only when one is given; otherwise the class default stays visible.
        A new empty list is created for each error, because a list used as a
        default value would be shared by every instance.

        Args:
            message: Explanation for the user. It must not contain secrets
                or internal details, because it is sent in the response.
            code: A more specific ``ErrorCode``, such as
                ``INSUFFICIENT_STOCK`` on a ``ConflictError``. Defaults to the
                class's code.
            details: Structured context for the client, one dict per item.
                Defaults to an empty list.
        """
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details if details is not None else []


class BadRequestError(AppError):
    """The request is well formed but can't be processed (400).

    Used when the input passes schema validation but is still unusable, for
    example a wrong or expired portal activation code, where the message is
    deliberately generic so an attacker can't tell which part was wrong.
    """

    status_code: int = 400
    code: str = ErrorCode.BAD_REQUEST


class AuthenticationError(AppError):
    """The caller isn't authenticated (401).

    Covers wrong credentials, a missing, invalid, or expired token, and an
    inactive account. Login failures use one generic message whether the
    email or the password was wrong, so accounts can't be discovered.
    """

    status_code: int = 401
    code: str = ErrorCode.AUTHENTICATION_FAILED


class PermissionDeniedError(AppError):
    """The caller is authenticated but not allowed to do this (403).

    Raised when the user's role lacks the required permission, and with
    ``code=ErrorCode.PASSWORD_CHANGE_REQUIRED`` while a temporary password
    must still be replaced. A record outside the user's scope is not a 403;
    it is a ``NotFoundError``.
    """

    status_code: int = 403
    code: str = ErrorCode.PERMISSION_DENIED


class NotFoundError(AppError):
    """The resource doesn't exist, or the user may not see it (404).

    Returning 404 instead of 403 for records outside the user's scope stops
    callers from probing which IDs exist, which prevents BOLA.
    """

    status_code: int = 404
    code: str = ErrorCode.NOT_FOUND


class ConflictError(AppError):
    """A business rule blocks the action (409).

    The input is valid, but the current state of the data forbids the
    action. Services pass a specific code such as
    ``INVALID_STATUS_TRANSITION``, ``APPOINTMENT_SLOT_TAKEN``, or
    ``INSUFFICIENT_STOCK`` so the client can react to each case.
    """

    status_code: int = 409
    code: str = ErrorCode.CONFLICT


class RateLimitedError(AppError):
    """Too many attempts in a short time (429).

    Raised by the login and portal activation rate limiters to slow down
    password guessing and code guessing.
    """

    status_code: int = 429
    code: str = ErrorCode.RATE_LIMITED


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """Build a response in the standard error format.

    Every handler goes through this function, so the body's shape is defined
    in exactly one place. The request ID is read defensively: it is missing
    when an error happens before the request-ID middleware runs, and an error
    handler must never raise an error of its own.

    Args:
        request: The request that failed; its state may hold the request ID.
        status_code: HTTP status of the response.
        code: Machine-readable error code, normally an ``ErrorCode`` member.
        message: Human-readable explanation, safe to show to the user.
        details: Structured context for the client. ``None`` becomes an
            empty list, so ``details`` is always a list in the response.

    Returns:
        A JSON response with body
        ``{"error": {"code", "message", "details", "request_id"}}``.
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details if details is not None else [],
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Convert a domain error raised by a service into its HTTP response.

    The status, code, message, and details all come from the exception, so
    this one handler serves every ``AppError`` subclass.

    Args:
        request: The request that failed.
        exc: The domain error raised by a service.

    Returns:
        The error response with the exception's own status and code.
    """
    return _error_response(request, exc.status_code, exc.code, exc.message, exc.details)


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert a Pydantic input validation failure into a 422 response.

    Each problem becomes one detail with the field path, a message, and the
    error type, for example ``{"field": "body.email", ...}``, so a form can
    show the message next to the right input. Pydantic's ``input`` value is
    deliberately left out: it can contain what the user typed, including
    passwords.

    Args:
        request: The request whose input failed validation.
        exc: FastAPI's validation error, listing every problem found.

    Returns:
        A 422 response with code ``VALIDATION_ERROR`` and one detail per
        problem.
    """
    details: list[dict[str, Any]] = []

    for error in exc.errors():
        loc = error["loc"]
        details.append(
            {
                "field": ".".join(str(part) for part in loc),
                "message": error["msg"],
                "type": error["type"],
            }
        )

    return _error_response(
        request,
        status_code=422,
        code=ErrorCode.VALIDATION_ERROR,
        message="The request contains invalid data.",
        details=details,
    )


# Maps the statuses Starlette and FastAPI's security helpers raise to error codes.
_STATUS_TO_ERROR_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.AUTHENTICATION_FAILED,
    403: ErrorCode.PERMISSION_DENIED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Convert Starlette's HTTP errors into the standard error format.

    These come from the framework rather than from services: an unknown URL
    (404), a known URL with the wrong method (405), and FastAPI's security
    helpers (401 and 403). Unlisted statuses fall back to ``INTERNAL_ERROR``
    for 5xx and ``BAD_REQUEST`` for 4xx, so ``code`` is always a string. The
    exception's headers are copied onto the response because clients need
    them: ``Allow`` on a 405 and ``WWW-Authenticate`` on a 401.

    Args:
        request: The request that failed.
        exc: Starlette's HTTP exception, with status, detail, and headers.

    Returns:
        An error response with the same status and any headers the exception
        carried.
    """
    status_code: int = exc.status_code
    default_code: ErrorCode = (
        ErrorCode.INTERNAL_ERROR if status_code >= 500 else ErrorCode.BAD_REQUEST
    )
    code: ErrorCode = _STATUS_TO_ERROR_CODE.get(status_code, default_code)
    message: str = str(exc.detail)
    headers = exc.headers

    response: JSONResponse = _error_response(request, status_code, code, message)

    if headers:
        response.headers.update(headers)

    return response


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Log an unplanned exception and return a generic 500 response.

    This is the last line of defence for bugs and outages. The full
    traceback goes to the log with the request ID, while the client gets a
    fixed message and the same request ID. The exception's text is never
    sent, because it can contain SQL, file paths, or patient data (plan §12).

    Args:
        request: The request that failed.
        exc: The unexpected exception. It isn't read here, because
            ``logger.exception`` records the active exception by itself, but
            FastAPI always passes it.

    Returns:
        A 500 response with code ``INTERNAL_ERROR`` and a generic message.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled error (request_id=%s)", request_id)

    return _error_response(
        request,
        status_code=500,
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all four error handlers to the application.

    ``main.py`` calls this once when it builds the app. Registration order
    doesn't matter: for each raised exception, FastAPI uses the handler for
    the closest class in that exception's hierarchy, so a ``ConflictError``
    reaches the ``AppError`` handler even though it is also an ``Exception``.

    Args:
        app: The FastAPI application to configure.

    Example:
        ``app = FastAPI(); register_exception_handlers(app)``
    """
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
