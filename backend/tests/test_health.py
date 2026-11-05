import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db

# Worded like libpq's message when nothing listens at the database's address: it names
# the host, and its hint is a second line.
DRIVER_MESSAGE = (
    'connection to server at "db.internal.example" (10.0.0.7), port 5432 failed: '
    "Connection refused\n"
    "\tIs the server running on that host and accepting TCP/IP connections?"
)


class BrokenSession:
    """Stands in for a session whose queries fail."""

    def execute(self, statement) -> None:
        """Fail the way an unreachable database does, with the driver's message.

        Args:
            statement: The statement the route tried to run; ignored.

        Raises:
            SQLAlchemyError: Always, carrying ``DRIVER_MESSAGE``, so the
                readiness check takes its failure path without a database
                being involved.
        """
        raise SQLAlchemyError(DRIVER_MESSAGE)


def test_liveness_returns_ok(client: TestClient) -> None:
    """The liveness check answers 200 with the fixed body.

    It must not depend on anything outside the process, so this passes even
    when the database is unreachable: a failure here means the application
    itself is stuck, and the platform should restart it.
    """
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_ok_when_the_database_answers(client: TestClient) -> None:
    """With the database reachable, the readiness check answers 200.

    Render's health check uses this route to decide whether a deployment
    receives traffic, so a healthy database must produce exactly the
    documented body. The database-down case returns 503 and is covered
    separately.
    """
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_unavailable_when_the_query_fails(
    app: FastAPI, client: TestClient
) -> None:
    """A failing query makes the readiness check answer 503, not 500.

    The session is replaced by a stub whose ``execute`` raises, so the
    failure is exercised without stopping the database. A 503 says "try
    again shortly", which is what a platform needs in order to wait instead
    of reporting a bug in the code.
    """
    app.dependency_overrides[get_db] = lambda: BrokenSession()

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_readiness_failure_keeps_the_driver_message_out_of_the_response(
    app: FastAPI, client: TestClient
) -> None:
    """A failed readiness check answers the fixed 503 body, without the driver's message.

    The stub fails with a message worded like libpq's, which names the
    database host. This route is public, so the client gets only the code
    ``SERVICE_UNAVAILABLE``, the fixed message, and the request ID it sent;
    the host appears nowhere in the response.
    """
    app.dependency_overrides[get_db] = lambda: BrokenSession()

    response = client.get(
        "/health/ready",
        headers={"X-Request-ID": "3f2c8a1e-9b4d-4c6e-8f00-123456789abc"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "The database is not reachable.",
            "details": [],
            "request_id": "3f2c8a1e-9b4d-4c6e-8f00-123456789abc",
        }
    }
    assert "db.internal.example" not in response.text


def test_readiness_failure_logs_the_driver_message_on_one_line(
    app: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed readiness check writes one warning with the cause and the request ID.

    The response leaves the driver's message out, so the log is the only
    place an operator can read why the database was unreachable, such as a
    wrong password or a stopped server. The warning carries the request ID
    the response names, which ties it to the request's own log line. It
    keeps the driver's two-line message on one line and has no traceback,
    because the check repeats every few seconds while the database is down.
    """
    app.dependency_overrides[get_db] = lambda: BrokenSession()

    with caplog.at_level(logging.WARNING, logger="app.api.health"):
        response = client.get("/health/ready")

    records = [record for record in caplog.records if record.name == "app.api.health"]
    request_id = response.json()["error"]["request_id"]

    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    message = records[0].getMessage()
    assert f"request_id={request_id}" in message
    assert "db.internal.example" in message
    assert "\n" not in message
