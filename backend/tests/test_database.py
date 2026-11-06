"""Tests for the database settings of the application and of the test suite.

On the application side, the engine in ``app/db/session.py`` must keep a
statement's values out of its error messages. On the test side, the
``test_engine`` fixture must point at the test database, the application's
engine must refuse to connect while the tests run, and ``db_session`` must
run each test that uses it inside a transaction that is rolled back when
the test ends, so that nothing a test commits outlives it.
"""

# Test framework: raises, which checks that a connection is refused.
import pytest

# Type of the test_engine fixture, the engine for the test database.
from sqlalchemy import Engine

# Wraps the raw SQL that creates, fills, and looks up the probe table.
from sqlalchemy import text

# Type of the db_session fixture, the session bound to the test's transaction.
from sqlalchemy.orm import Session

# The application's engine: its hide_parameters setting, and the refusal to connect.
from app.db.session import engine


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
