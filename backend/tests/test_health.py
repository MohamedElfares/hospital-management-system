"""Tests for the health check routes in ``app/api/health.py``.

``/health/live`` answers whenever the process runs, even while the
database is down. ``/health/ready`` answers 200 only while the database
answers, because plan §16 makes it Render's health check path, and Render
decides by its status code whether an instance gets traffic and when to
restart it. The tests run the database-down case without stopping the
database: they replace ``get_db`` with ``BrokenSession``, whose queries
fail with a message worded like the driver's. The liveness check must
still answer 200, and the readiness check must answer 503, keep that
message out of the public response, and write it to the log instead.
"""

# Log levels, for capturing the readiness check's warning and checking its level.
import logging

# Return type of the stub's execute, which always raises.
from typing import NoReturn

# Test framework: the type of the caplog fixture that captures the warning.
import pytest

# Type of the app fixture, on which the tests replace get_db with the stub.
from fastapi import FastAPI

# Sends requests to the health routes through the whole application.
from fastapi.testclient import TestClient

# Type of the statement the stub's execute receives, as Session.execute declares it.
from sqlalchemy import Executable

# Base class of SQLAlchemy's errors, the class the readiness check catches; the stub raises it.
from sqlalchemy.exc import SQLAlchemyError

# The dependency the tests replace with the stub.
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

    A test replaces ``get_db`` with a function that returns this stub. The
    readiness tests use it to run the failure path while the test database
    stays up, and the liveness test to show that its route never queries.
    The stub needs only ``execute``, the one method the readiness check
    calls. A real session fails at that same call: building one opens no
    connection, and its first ``execute`` raises ``OperationalError``,
    which subclasses the ``SQLAlchemyError`` raised here, the class the
    readiness check catches.
    """

    def execute(self, statement: Executable) -> NoReturn:
        """Fail as an unreachable database does, with the driver's message.

        Args:
            statement: The statement the route runs, ``SELECT 1``; ignored.

        Raises:
            SQLAlchemyError: Always, carrying ``DRIVER_MESSAGE``, so the
                readiness check takes its failure path, and the tests can
                look for the host in the response and in the log.
        """
        raise SQLAlchemyError(DRIVER_MESSAGE)


def test_liveness_returns_ok_while_the_database_is_unreachable(app: FastAPI) -> None:
    """The liveness check answers 200 with the fixed body while no query can succeed.

    The route must touch nothing outside the process, so that a failure
    there means the process itself is stuck or gone, and a database
    outage, such as a sleeping Neon instance, never makes it fail. The test
    therefore takes no ``client``, whose test session would answer any
    query. It replaces ``get_db`` with ``BrokenSession``, so a route that
    queried through ``get_db`` would fail, and the suite refuses every
    connection through the application's engine, so a route that opened
    its own session would fail too. Needing no database, the test also
    passes while the test database is down.
    """
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    client = TestClient(app)

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

    assert response.status_code == 503

    records = [record for record in caplog.records if record.name == "app.api.health"]
    request_id = response.json()["error"]["request_id"]

    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    message = records[0].getMessage()
    assert f"request_id={request_id}" in message
    assert "db.internal.example" in message
    assert "\n" not in message
