import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_unknown_path_returns_the_standard_404(client: TestClient) -> None:
    """An unknown URL is answered in the project's error format.

    Starlette raises this 404 itself, so a passing test proves the handlers
    are registered on the application: without them the body would be
    FastAPI's ``{"detail": "Not Found"}``, which no client of this API
    knows how to read.
    """
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_returns_405_with_an_allow_header(client: TestClient) -> None:
    """A known path called with the wrong method returns 405 and ``Allow``.

    The HTTP standard requires a 405 to name the methods that are allowed,
    and that header survives only because the handler copies the
    exception's headers onto the response.
    """
    response = client.delete("/health/live")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert response.headers["allow"] == "GET"


def test_response_carries_a_generated_request_id(client: TestClient) -> None:
    """Every response carries an ``X-Request-ID`` header, generated if needed.

    The client sent no ID here, so the middleware created one. Parsing it
    proves it is a real UUID rather than any placeholder string.
    """
    response = client.get("/health/live")

    assert uuid.UUID(response.headers["x-request-id"])


def test_client_request_id_is_echoed_back(client: TestClient) -> None:
    """An ID the client sends is reused, so one ID spans both systems.

    This is what lets a request be followed from the caller's logs into
    this application's logs and back out in the response.
    """
    response = client.get(
        "/health/live",
        headers={"X-Request-ID": "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"},
    )

    assert response.headers["x-request-id"] == "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"


def test_unexpected_error_returns_a_generic_500_with_the_request_id(app: FastAPI) -> None:
    """A crash answers with the fixed 500 body and the request ID, never its text.

    The route raises an exception whose message holds a fake password, the
    way a real bug's message can hold SQL, file paths, or patient data
    (plan §12). The client gets only the generic message, the code
    ``INTERNAL_ERROR``, and the request ID it sent, which is what finds the
    traceback in the log. Starlette re-raises the exception once the 500 is
    sent, so this client is built not to raise it again inside the test.
    """

    def crash() -> None:
        """Fail the way an unhandled bug does, with a secret in the message."""
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
