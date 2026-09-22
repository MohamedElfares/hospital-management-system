from sqlalchemy import text
from sqlalchemy.orm import Session


def test_engine_points_at_the_test_database(test_engine):
    """The suite connects to the test database, never the development one."""
    assert test_engine.url.database == "hms_test"


def test_a_row_written_in_one_test_is_not_visible_in_the_next(db_session: Session):
    """Work done through the session, including a commit, is visible in the test.

    The commit is the point: application code commits once per use case, and
    the fixture turns that into a savepoint release rather than a real
    commit, so the outer transaction can still undo it. The companion test
    below checks that the table is gone afterwards.
    """
    db_session.execute(text("CREATE TABLE IF NOT EXISTS rollback_prob (note text)"))
    db_session.execute(text("INSERT INTO rollback_prob VALUES ('first test')"))
    db_session.commit()

    rows = db_session.execute(text("SELECT COUNT(*) FROM rollback_prob")).scalar()
    assert rows == 1


def test_a_previous_test_left_no_table_behind(db_session: Session):
    """The table created and committed by the previous test no longer exists.

    PostgreSQL rolls back schema changes as well as rows, so the rollback in
    the fixture removes the table itself. Run on its own this test passes
    trivially, because nothing created the table in that run; its value is
    in a full run, where it shows that one test cannot leave data behind for
    the next one.
    """
    exists = db_session.execute(text("SELECT to_regclass('public.rollback_prob')")).scalar()

    assert exists is None
