from sqlalchemy import Engine
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import engine


def test_engine_points_at_the_test_database(test_engine: Engine) -> None:
    """The suite connects to the test database, never the development one."""
    assert test_engine.url.database == "hms_test"


def test_database_errors_leave_out_the_statement_values() -> None:
    """The application's engine keeps a statement's values out of its errors.

    SQLAlchemy writes the bound values into the text of every database
    error unless the engine sets ``hide_parameters``, and the 500 handler
    logs that text. Without the flag, a failed insert into ``users`` logs
    the email and the password hash. The flag is read from the engine
    itself, because a real failing statement would need the development
    database, which tests never touch.
    """
    assert engine.hide_parameters is True


def test_a_row_committed_in_a_test_is_visible_in_that_test(db_session: Session) -> None:
    """Work done through the session, including a commit, is visible in the test.

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

    PostgreSQL rolls back schema changes as well as rows, so the rollback in
    the fixture removes the table itself. Run on its own this test passes
    trivially, because nothing created the table in that run; its value is
    in a full run, where it shows that one test cannot leave data behind for
    the next one.
    """
    probe_table = db_session.execute(text("SELECT to_regclass('public.rollback_probe')")).scalar()

    assert probe_table is None
