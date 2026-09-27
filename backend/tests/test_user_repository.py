from factories import make_user
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.modules.users.repository import active_admin_exists
from app.modules.users.repository import add
from app.modules.users.repository import get_by_email


def test_an_added_user_can_be_found_by_email(db_session: Session) -> None:
    """A user added and flushed is returned by an email lookup, as the same row."""
    user = make_user()

    add(db_session, user)
    db_session.flush()

    database_user = get_by_email(db_session, user.email)

    assert database_user is not None
    assert database_user.id == user.id


def test_an_unknown_email_finds_no_user(db_session: Session) -> None:
    """An email nobody uses returns None, even when other users exist.

    Another user is saved first, so the test fails if the query ignored
    the email and returned any row.
    """
    user = make_user()

    add(db_session, user)
    db_session.flush()

    database_user = get_by_email(db_session, "unknownmail@example.com")

    assert database_user is None


def test_an_empty_table_has_no_active_admin(db_session: Session) -> None:
    """With no users at all, no active Admin exists: a fresh database allows ``create-admin``."""
    found = active_admin_exists(db_session)

    assert found is False


def test_an_active_admin_is_found(db_session: Session) -> None:
    """One active Admin is enough for the check to report True."""
    admin = make_user(role=Role.ADMIN)

    add(db_session, admin)
    db_session.flush()

    admin_exist = active_admin_exists(db_session)

    assert admin_exist is True


def test_an_inactive_admin_is_not_counted(db_session: Session) -> None:
    """A deactivated Admin doesn't count, so ``create-admin`` can recover access.

    This proves the ``is_active`` condition is part of the query.
    """
    admin = make_user(role=Role.ADMIN, is_active=False)

    add(db_session, admin)
    db_session.flush()

    admin_exist = active_admin_exists(db_session)

    assert admin_exist is False


def test_an_active_doctor_is_not_counted_as_an_admin(db_session: Session) -> None:
    """An active user with another role doesn't count as an Admin.

    This proves the role condition is part of the query.
    """
    doctor = make_user(role=Role.DOCTOR)

    add(db_session, doctor)
    db_session.flush()

    assert active_admin_exists(db_session) is False
