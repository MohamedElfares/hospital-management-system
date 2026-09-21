from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db


class BrokenSession:
    """Stands in for a session whose queries fail."""

    def execute(self, statement):
        """Fail the way a lost connection does.

        Args:
            statement: The statement the route tried to run; ignored.

        Raises:
            SQLAlchemyError: Always, so the readiness check takes its
                failure path without a database being involved.
        """
        raise SQLAlchemyError("connection failed")


def test_liveness_returns_ok(client: TestClient):
    """The liveness check answers 200 with the fixed body.

    It must not depend on anything outside the process, so this passes even
    when the database is unreachable: a failure here means the application
    itself is stuck, and the platform should restart it.
    """
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_ok_when_the_database_answers(client: TestClient):
    """With the database reachable, the readiness check answers 200.

    Render's health check uses this route to decide whether a deployment
    receives traffic, so a healthy database must produce exactly the
    documented body. The database-down case returns 503 and is covered
    separately.
    """
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_unavailable_when_the_query_fails(app: FastAPI, client: TestClient):
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
