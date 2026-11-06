"""Tests for the standard error format and the request ID it carries.

``app/core/errors.py`` turns every failure into one body, ``{"error":
{"code", "message", "details", "request_id"}}``, so a client reads every
error the same way, and the request-context middleware in
``app/core/logging.py`` gives each request the ID that body names. These
tests send requests through the whole application: errors the framework
raises itself (an unknown path, a wrong method), domain errors raised by
routes the tests add to their own application, and an unexpected crash.
They check the status, the code, the ``Allow`` header a 405 needs, the
challenge a 401 needs and a 403 leaves out, the request ID in the header
and in the body, and that a crash's text never reaches the client, while
its traceback reaches the log with the request ID. Validation errors are
tested with the sign-in and password-change requests in
``tests/test_auth_api.py``.
"""

# Log levels, for capturing the 500 handler's record and checking its level.
import logging

# Parses the generated request ID, which raises unless the value is a UUID.
import uuid

# Test framework: the type of the caplog fixture that captures the 500 handler's record.
import pytest

# Type of the app fixture, which the tests add their failing routes to.
from fastapi import FastAPI

# Sends requests through the whole application, middleware and error handlers included.
from fastapi.testclient import TestClient

# Domain error for a caller who isn't authenticated, which the API answers with 401.
from app.core.errors import AuthenticationError

# Domain error for a signed-in caller who isn't allowed to act, which the API answers with 403.
from app.core.errors import PermissionDeniedError


def test_unknown_path_returns_the_standard_404(client: TestClient) -> None:
    """An unknown URL is answered in the project's error format.

    Starlette's router raises this 404 itself, before any route runs, so
    the body can only come from the handler that
    ``register_exception_handlers`` installs for the framework's HTTP
    errors. Without that handler, FastAPI's default would answer
    ``{"detail": "Not Found"}``, which no client of this API knows how to
    read.
    """
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_returns_405_with_an_allow_header(client: TestClient) -> None:
    """A known path called with the wrong method returns 405 and ``Allow``.

    HTTP requires a 405 to list the methods the path allows, in an
    ``Allow`` header (RFC 9110). Starlette's router raises the 405 with
    that header, and it reaches the client only because the handler for
    the framework's HTTP errors copies the exception's headers onto the
    response it builds. FastAPI registers this route for GET alone, without
    HEAD, so the header is exactly ``GET``.
    """
    response = client.delete("/health/live")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert response.headers["allow"] == "GET"


def test_an_authentication_error_carries_a_bearer_challenge(
    app: FastAPI,
    client: TestClient,
) -> None:
    """An ``AuthenticationError`` answers 401 with ``WWW-Authenticate: Bearer``.

    HTTP requires every 401 to carry a challenge that names a way to
    authenticate (RFC 9110), and FastAPI's own 401, for a request without a
    bearer token, names ``Bearer``. The route raises the domain error
    itself, so the header can only come from ``AuthenticationError``, which
    declares it, through the handler, which copies an error's headers onto
    its response. Every ``AuthenticationError`` therefore gets it,
    whichever service raised it.
    """

    def refuse() -> None:
        """Refuse the caller as the auth service does when a token fails.

        Raises:
            AuthenticationError: Always, with the auth service's message for
                an invalid or expired token.
        """
        raise AuthenticationError("Invalid or expired token.")

    app.add_api_route("/api/v1/test/refuse", refuse, methods=["GET"])

    response = client.get("/api/v1/test/refuse")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_permission_error_carries_no_challenge(app: FastAPI, client: TestClient) -> None:
    """A ``PermissionDeniedError`` answers 403 without ``WWW-Authenticate``.

    A 403 means the caller is signed in but not allowed, so signing in
    again wouldn't help, and a challenge would only invite the client to
    try. HTTP allows the header on other responses (RFC 9110), but this API
    sends it with 401s alone, so the test fails if every domain error
    carries the challenge that ``AuthenticationError`` declares.
    """

    def forbid() -> None:
        """Refuse a signed-in caller as ``require_permission`` will.

        Raises:
            PermissionDeniedError: Always, with the default code,
                ``PERMISSION_DENIED``.
        """
        raise PermissionDeniedError("You don't have permission to do this.")

    app.add_api_route("/api/v1/test/forbid", forbid, methods=["GET"])

    response = client.get("/api/v1/test/forbid")

    assert response.status_code == 403
    assert "www-authenticate" not in response.headers


def test_response_carries_a_generated_request_id(client: TestClient) -> None:
    """A request sent without an ID gets a generated one in ``X-Request-ID``.

    The client sent no ID, so the middleware created one and returned it in
    the header, as it does for every response except a crash's 500, whose
    ID is only in the body. Parsing the value proves it is a UUID, not an
    empty or arbitrary string; how the middleware treats the IDs a client
    sends is tested in ``tests/test_logging.py``.
    """
    response = client.get("/health/live")

    assert uuid.UUID(response.headers["x-request-id"])


def test_client_request_id_is_echoed_back(client: TestClient) -> None:
    """An ID the client sends comes back unchanged, so one ID spans both systems.

    A proxy or the web app that sends its own ID can follow the request
    from its own logs into this application's log line, and back in the
    response. The ID sent is already in the form the middleware normalizes
    every ID to, so it comes back character for character.
    """
    response = client.get(
        "/health/live",
        headers={"X-Request-ID": "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"},
    )

    assert response.headers["x-request-id"] == "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"


def test_unexpected_error_returns_a_generic_500_with_the_request_id(app: FastAPI) -> None:
    """A crash answers with the fixed 500 body and the request ID, never its text.

    The route raises an exception whose message holds a fake password, as a
    real bug's message can hold SQL, file paths, or patient data. The
    client gets only the code ``INTERNAL_ERROR``, the generic message, and
    the request ID it sent, which leads to the traceback in the log. Plan
    §12 keeps stack traces out of error responses, and the handler keeps
    the exception's message out too. The ID is in the body because the
    middleware adds no header to a crash's response. Starlette re-raises
    the exception once the 500 is sent, so the test builds its own client
    with ``raise_server_exceptions=False``, which returns the response
    instead of raising the exception again inside the test.
    """

    def crash() -> None:
        """Fail as an unhandled bug does, with a secret in the message.

        Raises:
            RuntimeError: Always, with a fake password in its message.
        """
        raise RuntimeError("password=Leaked-Secret-1")

    app.add_api_route("/api/v1/test/crash", crash, methods=["GET"])
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/v1/test/crash",
        headers={"X-Request-ID": "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
            "details": [],
            "request_id": "3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
        }
    }
    assert "Leaked-Secret-1" not in response.text


def test_unexpected_error_logs_its_traceback_with_the_request_id(
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A crash writes one ERROR record that holds the exception and the request ID.

    The middleware writes no line for a request whose route raises, so this
    record, from the 500 handler, is the only log line that carries the
    request's ID, which plan §12 asks of every request, and the ID in the
    500 body is what finds it. The record holds the route's own exception,
    so the log shows its traceback, and its level is ERROR, which both the
    default ``INFO`` and CI's ``WARNING`` keep. The test builds its own
    client with ``raise_server_exceptions=False``, as the test above does,
    and takes the application from the ``app`` fixture, which builds it
    before the test body runs, so ``caplog`` still captures its records.
    """
    failure = RuntimeError("Unexpected failure in a route.")

    def crash() -> None:
        """Fail as an unhandled bug does, with the exception the test looks for.

        Raises:
            RuntimeError: Always, the test's ``failure``.
        """
        raise failure

    app.add_api_route("/api/v1/test/crash", crash, methods=["GET"])
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="app.core.errors"):
        response = client.get(
            "/api/v1/test/crash",
            headers={"X-Request-ID": "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"},
        )

    records = [record for record in caplog.records if record.name == "app.core.errors"]

    assert response.status_code == 500
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "request_id=3f2c8a1e-9b4d-4c6e-8f00-123456789abc" in records[0].getMessage()
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is failure
