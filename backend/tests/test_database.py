"""Tests for the database settings of the application and of the test suite.

On the application side, the engine in ``app/db/session.py`` must keep a
statement's values out of its error messages, and ``get_db`` must end each
request's session so that what the request didn't commit is rolled back.
On the test side, the
``test_engine`` fixture must point at the test database, the application's
engine must refuse to connect while the tests run, and ``db_session`` must
run each test that uses it inside a transaction that is rolled back when
the test ends, so that nothing a test commits outlives it.
"""

# Type of the real_get_db fixture: a function that opens one request's session.
from collections.abc import Callable

# What that function returns: get_db as a context manager, one with block per request.
from contextlib import AbstractContextManager

# Wraps get_db the way FastAPI runs a generator dependency.
from contextlib import contextmanager

# Test framework: fixtures, monkeypatch, and raises.
import pytest

# Builds a valid user for each request to save.
from factories import make_user

# Type of the test_engine fixture, the engine for the test database.
from sqlalchemy import Engine

# Wraps the raw SQL that creates, fills, and looks up the probe table.
from sqlalchemy import text

# Type of the db_session fixture, the session bound to the test's transaction.
from sqlalchemy.orm import Session

# Domain error that stands for a service refusing after its flush.
from app.core.errors import ConflictError

# The application's session factory; the stand-in builds its sessions with it.
from app.db.session import SessionLocal

# The application's engine: its hide_parameters setting, and the refusal to connect.
from app.db.session import engine

# The request-session dependency that API tests replace and these tests run.
from app.db.session import get_db

# Looks a saved user up in the test's session once the request has ended.
from app.modules.users.repository import get_user_by_email

FLUSHED_EMAIL = "flushed@example.com"
COMMITTED_EMAIL = "committed@example.com"
FAILED_EMAIL = "failed@example.com"


def test_engine_points_at_the_test_database(test_engine: Engine) -> None:
    """The suite's engine points at the database named ``hms_test``.

    That is the name the README, ``.env.example``, and CI give the test
    database. A ``TEST_DATABASE_URL`` copied from ``DATABASE_URL``, which
    names the development database ``hms`` in ``.env.example`` and CI,
    fails here, and so does a test database under any other name. The test
    reads only the URL; that no code reaches the development database
    through the application's engine is the next test's concern.
    """
    assert test_engine.url.database == "hms_test"


def test_connecting_through_the_application_engine_is_refused() -> None:
    """While the tests run, the application's engine refuses to connect.

    The engine is bound to ``DATABASE_URL``, the development database, and
    ``conftest.py`` refuses every connection through it before one opens,
    so a test that forgets ``client`` or ``get_test_db`` can't write
    there. Without the refusal, the connection opens, or fails with a
    database error where no development database is running, and the test
    fails either way. The ``with`` block closes a connection that opened,
    so a failing run leaves none behind.
    """
    with (
        pytest.raises(RuntimeError, match="must not connect to the development database"),
        engine.connect(),
    ):
        pass


def test_database_errors_leave_out_the_statement_values() -> None:
    """The application's engine keeps a statement's values out of its errors.

    When a statement fails, SQLAlchemy writes its bound values into the
    text of the error unless the engine sets ``hide_parameters``, and the
    500 handler logs that text with the traceback. Without the flag, an
    insert into ``users`` that fails unexpectedly logs the email and the
    password hash. The flag is read from the engine itself, because a real
    failing statement would need the development database, which the suite
    refuses to connect to.
    """
    assert engine.hide_parameters is True


@pytest.fixture
def real_get_db(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[], AbstractContextManager[Session]]:
    """Run the application's own ``get_db`` against the test's connection.

    API tests replace ``get_db`` with ``get_test_db``, so the tests below
    are the only ones that run the original. It opens its session from
    ``SessionLocal``, which is bound to the development database, so the
    fixture puts a stand-in into ``app.db.session``: a session from the
    real ``SessionLocal``, bound to the test's connection and joined with
    ``create_savepoint``, as ``db_session`` is. Closing such a session
    rolls back its savepoint, so whatever a request leaves uncommitted
    never reaches the database, and the test's outer rollback undoes the
    rest. FastAPI runs a generator dependency through
    ``contextlib.contextmanager``, so the fixture wraps ``get_db`` the same
    way, and each ``with`` block stands for one request.

    Args:
        db_session: The test's session, whose connection the request's
            session shares.
        monkeypatch: Puts the stand-in for ``SessionLocal`` in place for
            this test only.

    Returns:
        A function that returns ``get_db`` as a context manager.
    """
    connection = db_session.connection()
    monkeypatch.setattr(
        "app.db.session.SessionLocal",
        lambda: SessionLocal(bind=connection, join_transaction_mode="create_savepoint"),
    )
    return contextmanager(get_db)


def test_get_db_rolls_back_what_a_request_leaves_uncommitted(
    real_get_db: Callable[[], AbstractContextManager[Session]],
    db_session: Session,
) -> None:
    """A user a request flushes but never commits is gone once the request's session ends.

    ``get_db`` hands out its session inside a ``with`` block, and closing
    the session rolls back what wasn't committed, so a service that forgets
    ``commit()`` loses its work rather than leaving it in an open
    transaction. A ``get_db`` that never closed its session, or one that
    committed after the route, would leave the user in place.
    """
    with real_get_db() as session:
        session.add(make_user(email=FLUSHED_EMAIL))
        session.flush()

    assert get_user_by_email(db_session, FLUSHED_EMAIL) is None


def test_get_db_keeps_what_a_request_commits(
    real_get_db: Callable[[], AbstractContextManager[Session]],
    db_session: Session,
) -> None:
    """A user a request commits is still there once the request's session ends.

    Closing the session rolls back only what came after the commit, so a
    use case that completes keeps its work.
    """
    with real_get_db() as session:
        session.add(make_user(email=COMMITTED_EMAIL))
        session.commit()

    assert get_user_by_email(db_session, COMMITTED_EMAIL) is not None


def test_get_db_rolls_back_a_request_that_fails(
    real_get_db: Callable[[], AbstractContextManager[Session]],
    db_session: Session,
) -> None:
    """A user flushed before a request fails is rolled back, and the error still propagates.

    When a route raises, FastAPI throws the exception into the dependency
    at its ``yield``. The ``with`` block in ``get_db`` closes the session
    on the way out, so the failed request leaves nothing behind, and the
    error reaches the exception handlers unchanged.
    """
    with pytest.raises(ConflictError), real_get_db() as session:
        session.add(make_user(email=FAILED_EMAIL))
        session.flush()
        raise ConflictError("This request always fails after its flush.")

    assert get_user_by_email(db_session, FAILED_EMAIL) is None


def test_a_row_committed_in_a_test_is_visible_in_that_test(db_session: Session) -> None:
    """A table and a row a test creates and commits are there for the rest of the test.

    The commit is the point: application code commits once per use case, and
    the fixture turns that into a savepoint release rather than a real
    commit, so the outer transaction can still undo it. The companion test
    below checks that the table is gone afterwards.
    """
    db_session.execute(text("CREATE TABLE IF NOT EXISTS rollback_probe (note text)"))
    db_session.execute(text("INSERT INTO rollback_probe VALUES ('first test')"))
    db_session.commit()

    row_count = db_session.execute(text("SELECT COUNT(*) FROM rollback_probe")).scalar()
    assert row_count == 1


def test_a_previous_test_left_no_table_behind(db_session: Session) -> None:
    """The table created and committed by the previous test no longer exists.

    PostgreSQL rolls back schema changes as well as rows, so the rollback
    that ends the previous test removes the table itself. Run on its own
    this test passes trivially, because nothing created the table in that
    run; its value is in a full run, where it runs after its companion and
    shows that one test cannot leave data behind for the next one.
    ``to_regclass`` returns NULL, which arrives as ``None``, when no table
    has that name.
    """
    probe_table = db_session.execute(text("SELECT to_regclass('public.rollback_probe')")).scalar()

    assert probe_table is None
