import uuid

from factories import make_user
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.modules.users.repository import create_user
from app.modules.users.repository import exists_active_admin
from app.modules.users.repository import get_user_by_email
from app.modules.users.repository import get_user_by_id
from app.modules.users.repository import get_user_by_id_for_update


def test_an_added_user_can_be_found_by_email(db_session: Session) -> None:
    """A user added and flushed is returned by an email lookup, as the same row."""
    user = make_user()

    create_user(db_session, user)
    db_session.flush()

    database_user = get_user_by_email(db_session, user.email)

    assert database_user is not None
    assert database_user.id == user.id


def test_an_unknown_email_finds_no_user(db_session: Session) -> None:
    """An email nobody uses returns None, even when other users exist.

    Another user is saved first, so the test fails if the query ignored
    the email and returned any row.
    """
    user = make_user()

    create_user(db_session, user)
    db_session.flush()

    database_user = get_user_by_email(db_session, "unknownmail@example.com")

    assert database_user is None


def test_an_empty_table_has_no_active_admin(db_session: Session) -> None:
    """With no users at all, no active Admin exists: a fresh database allows ``create-admin``."""
    found = exists_active_admin(db_session)

    assert found is False


def test_an_active_admin_is_found(db_session: Session) -> None:
    """One active Admin is enough for the check to report True."""
    admin = make_user(role=Role.ADMIN)

    create_user(db_session, admin)
    db_session.flush()

    admin_exist = exists_active_admin(db_session)

    assert admin_exist is True


def test_an_inactive_admin_is_not_counted(db_session: Session) -> None:
    """A deactivated Admin doesn't count, so ``create-admin`` can recover access.

    This proves the ``is_active`` condition is part of the query.
    """
    admin = make_user(role=Role.ADMIN, is_active=False)

    create_user(db_session, admin)
    db_session.flush()

    admin_exist = exists_active_admin(db_session)

    assert admin_exist is False


def test_an_active_doctor_is_not_counted_as_an_admin(db_session: Session) -> None:
    """An active user with another role doesn't count as an Admin.

    This proves the role condition is part of the query.
    """
    doctor = make_user(role=Role.DOCTOR)

    create_user(db_session, doctor)
    db_session.flush()

    assert exists_active_admin(db_session) is False


def test_an_added_user_can_be_found_by_id(db_session: Session) -> None:
    """A saved user is returned by an id lookup, and not the other saved user.

    The decoy is added first, so a lookup that ignored the id and returned
    the first row would return the decoy and fail. The session is emptied
    before the lookup, so the user is read from the database, not from the
    session's memory.
    """
    decoy_user = make_user(email="other@example.com")
    user = make_user()

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    result = get_user_by_id(db_session, user.id)

    assert result is not None
    assert result.id == user.id


def test_an_unknown_id_finds_no_user(db_session: Session) -> None:
    """An id that no user has returns None, even with users in the table.

    Because two users exist, any lookup that returned "some user" instead
    of the matching one would fail here, whatever order the rows come in.
    """
    user = make_user()
    decoy_user = make_user(email="other@example.com")

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    assert get_user_by_id(db_session, uuid.uuid4()) is None


def test_a_locked_lookup_finds_the_user_by_id(db_session: Session) -> None:
    """The locking lookup returns the user with the id, not the decoy saved first.

    The session is emptied before the lookup, so the user is read from the
    database. The lock itself is tested in ``test_auth_concurrency.py``,
    where a second connection can wait for it.
    """
    decoy_user = make_user(email="other@example.com")
    user = make_user()

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    result = get_user_by_id_for_update(db_session, user.id)

    assert result is not None
    assert result.id == user.id


def test_a_locked_lookup_of_an_unknown_id_finds_no_user(db_session: Session) -> None:
    """An id that no user has returns None from the locking lookup too."""
    db_session.add(make_user())
    db_session.flush()
    db_session.expunge_all()

    assert get_user_by_id_for_update(db_session, uuid.uuid4()) is None


def test_a_locked_lookup_reads_the_user_as_the_database_holds_it_now(db_session: Session) -> None:
    """The locking lookup replaces a copy the session holds with the stored row.

    The name changes in the database through plain SQL, which leaves the
    session's copy as it was. The ordinary lookup returns that stale copy
    from memory, which shows the setup works; the locking lookup reads the
    row again and updates the same object, so a caller that locks a user
    always sees the latest committed values, such as a new password hash.
    """
    user = make_user(full_name="Old Name")
    db_session.add(user)
    db_session.flush()

    db_session.execute(
        text("UPDATE users SET full_name = 'New Name' WHERE id = :id"),
        {"id": user.id},
    )

    stale_copy = get_user_by_id(db_session, user.id)

    assert stale_copy is not None
    assert stale_copy.full_name == "Old Name"

    result = get_user_by_id_for_update(db_session, user.id)

    assert result is user
    assert user.full_name == "New Name"
