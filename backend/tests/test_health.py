"""Tests for the health check routes in ``app/api/health.py``.

``/health/live`` answers whenever the process runs. ``/health/ready``
answers 200 only while the database answers, because plan §16 makes it
Render's health check path, and Render decides by its status code whether
an instance gets traffic and when to restart it. The tests run the
database-down case without stopping the database: they replace ``get_db``
with ``BrokenSession``, whose queries fail with a message worded like the
driver's, and check that the 503 keeps that message out of the public
response and writes it to the log instead.
"""

# Log levels, for capturing the readiness check's warning and checking its level.
import logging

# Test framework: the type of the caplog fixture that captures the warning.
import pytest

# Type of the app fixture, on which the failure tests replace get_db with the stub.
from fastapi import FastAPI

# Sends requests to the health routes through the whole application.
from fastapi.testclient import TestClient

# Base class of SQLAlchemy's errors, the class the readiness check catches; the stub raises it.
from sqlalchemy.exc import SQLAlchemyError

# The dependency the failure tests replace with the stub.
from app.db.session import get_db

# Worded like libpq's message when nothing listens at the database's address, because the
# tests check two things about a real one: it names the host, which must stay out of the
# response, and its hint is a second line, which the log must keep on one.
DRIVER_MESSAGE = (
    'connection to server at "db.internal.example" (10.0.0.7), port 5432 failed: '
    "Connection refused\n"
    "\tIs the server running on that host and accepting TCP/IP connections?"
)


class BrokenSession:
    """Stand-in for a session whose queries fail, as when the database is down.

    A test replaces ``get_db`` with a function that returns this stub, so
    the readiness check's failure path runs while the test database stays
    up. The stub needs only ``execute``, the one method the route calls. A
    real session fails at that same call: building one opens no
    connection, and its first ``execute`` raises ``OperationalError``,
    which subclasses the ``SQLAlchemyError`` raised here, the class the
    route catches.
    """

    def execute(self, statement) -> None:
        """Fail as an unreachable database does, with the driver's message.

        Args:
            statement: The statement the route runs, ``SELECT 1``; ignored.

        Raises:
            SQLAlchemyError: Always, carrying ``DRIVER_MESSAGE``, so the
                readiness check takes its failure path, and the tests can
                look for the host in the response and in the log.
        """
        raise SQLAlchemyError(DRIVER_MESSAGE)


def test_liveness_returns_ok(client: TestClient) -> None:
    """The liveness check answers 200 with the fixed body.

    The route touches nothing outside the process, so it answers even while
    the database is down, and a failure there means the process itself is
    stuck or gone. This test runs through ``client``, whose test database
    is up, so it checks the answer, not that the route stays clear of the
    database.
    """
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_ok_when_the_database_answers(client: TestClient) -> None:
    """With the database reachable, the readiness check answers 200 and the fixed body.

    Render counts any 2xx or 3xx answer as a passed check, so the 200 is
    what lets a new deployment receive traffic. The body is pinned too,
    because the route's response model documents it. The database-down
    case is covered by the tests below.
    """
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_unavailable_when_the_query_fails(
    app: FastAPI, client: TestClient
) -> None:
    """A failing query makes the readiness check answer 503, not 500.

    ``get_db`` is replaced by ``BrokenSession``, so the failure runs
    without stopping the database. Render counts both statuses as a failed
    check, but a 503 tells a monitoring system or a client that a
    dependency is down for now, while a 500 would report a bug in the code.
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
    database host. The route is public, so the body holds only the code
    ``SERVICE_UNAVAILABLE``, the fixed message, and the request ID the
    client sent, and the host appears nowhere in it.
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
    because Render repeats the check every few seconds while the database
    is down.
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
