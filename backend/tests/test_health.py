from fastapi.testclient import TestClient


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
