"""Tests for the session fixtures in ``conftest.py``.

API and CLI tests trust ``get_test_db`` to end the test's session the way
the application ends a request's or a command's, and every test trusts
``db_session`` to have the application's session options. These tests
check both. The request side runs through routes added to the test's own
application, which stand for services that commit, forget to commit, or
fail after a flush; the command side and the session's options are
checked on the session directly.
"""

# Type of the user ID in the path of the routes that read a user back.
import uuid

# Type of the get_test_db fixture, a function that returns a generator.
from collections.abc import Callable

# Type of what get_test_db's stand-in returns when called: a generator of one session.
from collections.abc import Iterator

# Turns get_test_db into a context manager, as CLI tests do for SessionLocal.
from contextlib import contextmanager

# Date and time type of the sign-in time the tests give a user.
from datetime import datetime

# Attaches the get_db dependency to each test route's session parameter.
from typing import Annotated

# Asia/Dubai time zone, so the sign-in time differs from its UTC form.
from zoneinfo import ZoneInfo

# Test framework: the fixture decorator and the usefixtures mark.
import pytest

# Builds a valid user, so a test sets only the fields it is about.
from factories import make_user

# Declares the get_db dependency of each test route.
from fastapi import Depends

# Type of the app fixture, which the test routes are added to.
from fastapi import FastAPI

# Type of the client fixture, which sends requests to the test routes.
from fastapi.testclient import TestClient

# SQL count(), for counting the users saved with an email.
from sqlalchemy import func

# Builds the counting query.
from sqlalchemy import select

# Type of the sessions the routes receive and the tests query.
from sqlalchemy.orm import Session

# Domain error the failing route raises, which the API answers with 409.
from app.core.errors import ConflictError

# The application's session factory, whose session class db_session must be.
from app.db.session import SessionLocal

# The dependency the test routes ask for, and the client replaces.
from app.db.session import get_db

# The ORM model the routes save and the tests count.
from app.modules.users.models import User

COMMIT_URL = "/api/v1/test/commit-a-user"
FLUSH_URL = "/api/v1/test/flush-a-user"
FAIL_URL = "/api/v1/test/flush-a-user-then-fail"

COMMITTED_EMAIL = "committed@example.com"
UNCOMMITTED_EMAIL = "uncommitted@example.com"
FAILED_EMAIL = "failed@example.com"
SETUP_EMAIL = "setup@example.com"

# 17:00 UTC, given in the hospital's default time zone.
DUBAI_SIGN_IN = datetime(2026, 11, 5, 21, 0, tzinfo=ZoneInfo("Asia/Dubai"))


@pytest.fixture
def user_routes(app: FastAPI) -> None:
    """Add routes that save a user in three ways, and two that read a user back.

    Each saving route stands for a service: one that commits, one that
    forgets to, and one that fails after it flushed. The reading routes
    show what a request's session sees of the test's setup. Every route
    asks for ``get_db``, so, through the override ``client`` installs, it
    gets the test's session from ``get_test_db``. The routes are added to
    this test's own application only, so they never leak into another
    test.

    Args:
        app: The application built for this test.
    """

    def commit_a_user(db: Annotated[Session, Depends(get_db)]) -> None:
        """Save a user and commit, as a use case that completes does.

        Args:
            db: The request's session, from ``get_db``.
        """
        db.add(make_user(email=COMMITTED_EMAIL))
        db.commit()

    def flush_a_user(db: Annotated[Session, Depends(get_db)]) -> None:
        """Save a user and flush it but never commit, as a service that forgets to does.

        The flush sends the ``INSERT``, so the row exists in the request's
        transaction until the rollback that ends the request removes it.

        Args:
            db: The request's session, from ``get_db``.
        """
        db.add(make_user(email=UNCOMMITTED_EMAIL))
        db.flush()

    def flush_a_user_then_fail(db: Annotated[Session, Depends(get_db)]) -> None:
        """Save a user and flush it, then refuse with a conflict before any commit.

        Args:
            db: The request's session, from ``get_db``.

        Raises:
            ConflictError: Always, after the flush; the API answers 409.
        """
        db.add(make_user(email=FAILED_EMAIL))
        db.flush()
        raise ConflictError("This test route always fails after its flush.")

    def find_user(user_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> dict[str, bool]:
        """Say whether the request's session finds the user with ``user_id``.

        Args:
            user_id: ID of the user to look for, from the path.
            db: The request's session, from ``get_db``.

        Returns:
            ``{"found": True}`` when the user exists, else ``{"found": False}``.
        """
        return {"found": db.get(User, user_id) is not None}

    def read_last_login(
        user_id: uuid.UUID,
        db: Annotated[Session, Depends(get_db)],
    ) -> dict[str, str]:
        """Return the user's sign-in time exactly as the request's session reads it.

        Args:
            user_id: ID of the user to read, from the path. The user must
                exist and have a sign-in time.
            db: The request's session, from ``get_db``.

        Returns:
            ``{"last_login_at": ...}``, the time in ISO 8601 form with its
            UTC offset, so a test can tell +04:00 from +00:00.
        """
        user = db.get(User, user_id)
        return {"last_login_at": user.last_login_at.isoformat()}

    app.add_api_route(COMMIT_URL, commit_a_user, methods=["POST"], status_code=204)
    app.add_api_route(FLUSH_URL, flush_a_user, methods=["POST"], status_code=204)
    app.add_api_route(FAIL_URL, flush_a_user_then_fail, methods=["POST"], status_code=204)
    app.add_api_route("/api/v1/test/users/{user_id}", find_user, methods=["GET"])
    app.add_api_route("/api/v1/test/users/{user_id}/last-login", read_last_login, methods=["GET"])


def _count_users(db_session: Session, email: str) -> int | None:
    """Count the users saved with ``email``, as the database holds them now.

    The count is a query, so it reports the rows the test's transaction
    holds at that moment: a row a request flushed and then rolled back is
    not counted.

    Args:
        db_session: The test's session.
        email: Email to count, as stored.

    Returns:
        The number of users with that email; ``scalar`` is typed as
        possibly ``None``, though a count always returns a row.
    """
    return db_session.scalar(select(func.count()).select_from(User).where(User.email == email))


@pytest.mark.usefixtures("user_routes")
def test_a_request_loses_the_work_it_never_commits(client: TestClient, db_session: Session) -> None:
    """A user a request flushes but never commits is gone once the request ends.

    The application's ``get_db`` closes the request's session, and closing
    rolls back whatever wasn't committed. ``get_test_db``, which ``client``
    puts in place of ``get_db``, rolls back the same way, so a service that
    forgets ``commit()`` fails the API test that reads its result, instead
    of passing with work that production would lose.
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


def test_the_test_session_is_built_by_the_applications_session_factory(
    db_session: Session,
) -> None:
    """The test session comes from ``SessionLocal``, so it has every option the application's has.

    An option added to ``SessionLocal`` later then reaches the tests too,
    instead of the tests quietly running with SQLAlchemy's defaults.
    ``sessionmaker`` builds a subclass of ``Session`` of its own, its
    ``class_``, so a plain ``Session`` fails the check even when it is
    given the same options.
    """
    assert isinstance(db_session, SessionLocal.class_)


def test_the_test_session_keeps_the_values_it_was_given_after_a_commit(
    db_session: Session,
) -> None:
    """A committed object keeps the values it was given, as in the application's sessions.

    ``SessionLocal`` sets ``expire_on_commit=False``, so a service that
    commits and then returns an object hands the router the values it set.
    A sign-in time given in Dubai time therefore still reads +04:00 after
    the commit, instead of coming back from the database as UTC.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()
    user.last_login_at = DUBAI_SIGN_IN

    db_session.commit()

    assert user.last_login_at.isoformat() == "2026-11-05T21:00:00+04:00"


@pytest.mark.usefixtures("user_routes")
def test_a_request_reads_the_tests_setup_from_the_database(
    client: TestClient,
    db_session: Session,
) -> None:
    """A request reads the test's setup as the database returns it, as a new session would.

    The test gives a user a sign-in time in Dubai time. The database keeps
    the instant and returns it in UTC, so a production request, with a
    session of its own, would read the UTC value. The stand-in expires the
    test's objects before the request, so the request reads that value
    too, rather than the test's object as it is in memory.
    """
    user = make_user(email=SETUP_EMAIL)
    db_session.add(user)
    db_session.flush()
    user.last_login_at = DUBAI_SIGN_IN

    response = client.get(f"/api/v1/test/users/{user.id}/last-login")

    assert response.status_code == 200
    assert response.json() == {"last_login_at": "2026-11-05T17:00:00+00:00"}
