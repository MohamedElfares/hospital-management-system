import uuid
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import pytest
from factories import make_user
from fastapi import Depends
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db.session import get_db
from app.modules.users.models import User

COMMIT_URL = "/api/v1/test/commit-a-user"
FLUSH_URL = "/api/v1/test/flush-a-user"
FAIL_URL = "/api/v1/test/flush-a-user-then-fail"

COMMITTED_EMAIL = "committed@example.com"
UNCOMMITTED_EMAIL = "uncommitted@example.com"
FAILED_EMAIL = "failed@example.com"
SETUP_EMAIL = "setup@example.com"


@pytest.fixture
def user_routes(app: FastAPI) -> None:
    """Add routes that save a user in three ways, and one that looks a user up.

    Each saving route stands for a service: one that commits, one that
    forgets to, and one that fails after it flushed. They are added to this
    test's own application only, so they never leak into another test.

    Args:
        app: The application built for this test.
    """

    def commit_a_user(db: Annotated[Session, Depends(get_db)]) -> None:
        """Save a user and commit, as a use case that completes does."""
        db.add(make_user(email=COMMITTED_EMAIL))
        db.commit()

    def flush_a_user(db: Annotated[Session, Depends(get_db)]) -> None:
        """Save a user and flush it but never commit, as a service that forgets to does."""
        db.add(make_user(email=UNCOMMITTED_EMAIL))
        db.flush()

    def flush_a_user_then_fail(db: Annotated[Session, Depends(get_db)]) -> None:
        """Save a user and flush it, then refuse with a conflict before any commit."""
        db.add(make_user(email=FAILED_EMAIL))
        db.flush()
        raise ConflictError("This test route always fails after its flush.")

    def find_user(user_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> dict[str, bool]:
        """Say whether the request's session finds the user with ``user_id``."""
        return {"found": db.get(User, user_id) is not None}

    app.add_api_route(COMMIT_URL, commit_a_user, methods=["POST"], status_code=204)
    app.add_api_route(FLUSH_URL, flush_a_user, methods=["POST"], status_code=204)
    app.add_api_route(FAIL_URL, flush_a_user_then_fail, methods=["POST"], status_code=204)
    app.add_api_route("/api/v1/test/users/{user_id}", find_user, methods=["GET"])


def _count_users(db_session: Session, email: str) -> int | None:
    """Count the users saved with ``email``, as the database holds them now."""
    return db_session.scalar(select(func.count()).select_from(User).where(User.email == email))


@pytest.mark.usefixtures("user_routes")
def test_a_request_loses_the_work_it_never_commits(client: TestClient, db_session: Session) -> None:
    """A user a request flushes but never commits is gone once the request ends.

    The application's ``get_db`` closes the request's session, and closing
    rolls back whatever wasn't committed. The test client does the same, so
    a service that forgets ``commit()`` fails the API test that reads its
    result, instead of passing with work that production would lose.
    """
    response = client.post(FLUSH_URL)

    assert response.status_code == 204
    assert _count_users(db_session, UNCOMMITTED_EMAIL) == 0


@pytest.mark.usefixtures("user_routes")
def test_a_request_keeps_the_work_it_commits(client: TestClient, db_session: Session) -> None:
    """A user a request commits is still there for the test to read.

    The rollback that ends the request undoes only what came after its
    commit, so committed work stays in the test's transaction until the
    test ends.
    """
    response = client.post(COMMIT_URL)

    assert response.status_code == 204
    assert _count_users(db_session, COMMITTED_EMAIL) == 1


@pytest.mark.usefixtures("user_routes")
def test_a_failed_request_loses_the_work_it_flushed(
    client: TestClient,
    db_session: Session,
) -> None:
    """A user flushed before a request fails is rolled back with the request.

    The route answers 409 after its flush, as a service that refuses half
    way would. The rollback runs however the request ends, as closing a
    real session does, so nothing the failed request did is left.
    """
    response = client.post(FAIL_URL)

    assert response.status_code == 409
    assert _count_users(db_session, FAILED_EMAIL) == 0


@pytest.mark.usefixtures("user_routes")
def test_a_request_finds_the_tests_setup_and_leaves_it_in_place(
    client: TestClient,
    db_session: Session,
) -> None:
    """A user the test only flushed is visible to the request and is still there after it.

    The test's setup is committed before the request, as it would already
    be in the database before a real one, so the rollback that ends the
    request can't remove it.
    """
    user = make_user(email=SETUP_EMAIL)
    db_session.add(user)
    db_session.flush()

    response = client.get(f"/api/v1/test/users/{user.id}")

    assert response.status_code == 200
    assert response.json() == {"found": True}
    assert _count_users(db_session, SETUP_EMAIL) == 1


def test_a_command_loses_the_work_it_never_commits(
    get_test_db: Callable[[], Iterator[Session]],
    db_session: Session,
) -> None:
    """Used in place of ``SessionLocal``, the stand-in rolls back what a command didn't commit.

    CLI tests wrap ``get_test_db`` with ``contextmanager`` and put it in
    place of ``SessionLocal``, and a command opens its session with
    ``with SessionLocal() as session``, as ``create-admin`` does. The user
    the block flushes is gone once the block ends.
    """
    session_local = contextmanager(get_test_db)

    with session_local() as session:
        session.add(make_user(email=UNCOMMITTED_EMAIL))
        session.flush()

    assert _count_users(db_session, UNCOMMITTED_EMAIL) == 0
