import uuid

from fastapi.testclient import TestClient


def test_unknown_path_returns_the_standard_404(client: TestClient):
    """An unknown URL is answered in the project's error format.

    Starlette raises this 404 itself, so a passing test proves the handlers
    are registered on the application: without them the body would be
    FastAPI's ``{"detail": "Not Found"}``, which no client of this API
    knows how to read.
    """
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_returns_405_with_an_allow_header(client: TestClient):
    """A known path called with the wrong method returns 405 and ``Allow``.

    The HTTP standard requires a 405 to name the methods that are allowed,
    and that header survives only because the handler copies the
    exception's headers onto the response.
    """
    response = client.delete("/health/live")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert response.headers["allow"] == "GET"


def test_response_carries_a_generated_request_id(client: TestClient):
    """Every response carries an ``X-Request-ID`` header, generated if needed.

    The client sent no ID here, so the middleware created one. Parsing it
    proves it is a real UUID rather than any placeholder string.
    """
    response = client.get("/health/live")

    assert uuid.UUID(response.headers["x-request-id"])


def test_client_request_id_is_echoed_back(client: TestClient):
    """An ID the client sends is reused, so one ID spans both systems.

    This is what lets a request be followed from the caller's logs into
    this application's logs and back out in the response.
    """
    response = client.get(
        "/health/live",
        headers={"X-Request-ID": "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"},
    )

    assert response.headers["x-request-id"] == "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"
