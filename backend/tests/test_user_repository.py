"""Tests for the users repository: the queries behind every account lookup.

The tests call the repository's functions directly with ``db_session``,
the test's own session, and flush what they save, so every query runs
against PostgreSQL inside the test's transaction. ``get_user_by_email``
finds an account by its stored email, and only by that exact text, so
``%`` and ``_`` in a typed email are no wildcards; ``get_user_by_id`` and
``get_user_by_id_for_update`` find one by its ID. Each returns None for
an email or ID that no account has, with accounts in the table, and a
decoy saved first shows that the ID lookups filter on the ID rather than
returning the first row. The locking lookup also reads the row again
when the session holds a copy, so a caller that locks a user sees what
the database holds. ``exists_active_admin`` reports True for an active
Admin, and False for an empty table, a deactivated Admin, an active
account of every other role, and a deactivated Admin beside an active
Doctor, the recovery case ``create-admin`` exists for. ``create_user``
only adds the user to the session; the test's flush writes it, as the
users service's own flush does.

The lock that ``get_user_by_id_for_update`` takes can only be seen from a
second connection, so ``tests/test_auth_concurrency.py`` tests it, in
races where a reuse alarm or a password change waits for a refresh or a
sign-in that holds it. The users service's lookups, which normalize a
typed email before this query sees it, are tested in
``tests/test_user_service.py``.
"""

# Random UUIDs; an ID that no saved account has.
import uuid

# Test framework: parametrize runs the role check for every role but Admin, and the wildcards.
import pytest

# Builds an unsaved User; the tests save the accounts they look up, and decoys beside them.
from factories import make_user

# Raw SQL; changes a stored name while the session's copy keeps the old one.
from sqlalchemy import text

# Type of the db_session fixture.
from sqlalchemy.orm import Session

# The role enum; builds the Admins and the other roles that the active-Admin check tells apart.
from app.core.permissions import Role

# Adds a new user to the session; under test with the email lookup that finds it.
from app.modules.users.repository import create_user

# The check that create-admin runs before it creates an Admin, under test.
from app.modules.users.repository import exists_active_admin

# The email lookup that sign-in reaches through the users service, under test.
from app.modules.users.repository import get_user_by_email

# The plain ID lookup, under test; it also returns the stale copy the locking lookup replaces.
from app.modules.users.repository import get_user_by_id

# The locking ID lookup that auth takes before it changes a user's sessions, under test.
from app.modules.users.repository import get_user_by_id_for_update


def test_an_added_user_can_be_found_by_email(db_session: Session) -> None:
    """A user added and flushed is returned by an email lookup, as the same row.

    A query by email always reaches the database, even though the session
    holds the user, so the condition on the email is what finds the row;
    the next test shows that the query doesn't return a row for any email.
    """
    user = make_user()

    create_user(db_session, user)
    db_session.flush()

    found_user = get_user_by_email(db_session, user.email)

    assert found_user is not None
    assert found_user.id == user.id


def test_an_unknown_email_finds_no_user(db_session: Session) -> None:
    """An email nobody uses returns None, even when other users exist.

    Another user is saved first, so the test fails if the query ignored
    the email and returned any row.
    """
    user = make_user()

    create_user(db_session, user)
    db_session.flush()

    found_user = get_user_by_email(db_session, "unknownmail@example.com")

    assert found_user is None


@pytest.mark.parametrize(
    "email",
    [
        pytest.param("%@example.com", id="percent"),
        pytest.param("t_st@example.com", id="underscore"),
    ],
)
def test_a_wildcard_character_in_the_email_matches_no_other_address(
    db_session: Session,
    email: str,
) -> None:
    """An email with ``%`` or ``_`` finds no account but one with that exact text.

    The ``Email`` rule accepts both characters before the @, so sign-in
    passes them to this lookup. ``LIKE`` and ``ILIKE``, the usual way to
    make a lookup case-insensitive, read them as wildcards: there,
    ``%@example.com`` and ``t_st@example.com`` would find
    ``test@example.com``, and sign-in would check the typed password
    against that account. The lookup compares with ``=``, so neither finds
    the saved account.
    """
    create_user(db_session, make_user())
    db_session.flush()

    assert get_user_by_email(db_session, email) is None


def test_an_empty_table_has_no_active_admin(db_session: Session) -> None:
    """With no users at all, no active Admin exists: a fresh database allows ``create-admin``."""
    has_active_admin = exists_active_admin(db_session)

    assert has_active_admin is False


def test_an_active_admin_is_found(db_session: Session) -> None:
    """One active Admin is enough for the check to report True.

    The account is active through the column's server default, as every
    new account is.
    """
    admin = make_user(role=Role.ADMIN)

    create_user(db_session, admin)
    db_session.flush()

    has_active_admin = exists_active_admin(db_session)

    assert has_active_admin is True


def test_an_inactive_admin_is_not_counted(db_session: Session) -> None:
    """A deactivated Admin doesn't count, so ``create-admin`` can recover access.

    This proves the ``is_active`` condition is part of the query.
    """
    admin = make_user(role=Role.ADMIN, is_active=False)

    create_user(db_session, admin)
    db_session.flush()

    has_active_admin = exists_active_admin(db_session)

    assert has_active_admin is False


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.ADMIN])
def test_an_active_user_of_another_role_is_not_counted_as_an_admin(
    db_session: Session,
    role: Role,
) -> None:
    """An active user of any role but Admin doesn't count as an Admin.

    This proves the role condition is part of the query, and that it names
    Admin alone: every other role is tried, so a check that also counted a
    Manager, the other role that manages accounts, fails its case.
    """
    user = make_user(role=role)

    create_user(db_session, user)
    db_session.flush()

    assert exists_active_admin(db_session) is False


def test_an_inactive_admin_beside_an_active_doctor_is_not_counted(db_session: Session) -> None:
    """A deactivated Admin next to an active Doctor still means no active Admin.

    This is the recovery case ``create-admin`` exists for: every Admin is
    deactivated while the rest of the staff are still active. The check
    must find one account that is both an Admin and active, so a query
    that took the role from one row and the active flag from another would
    report an active Admin here and refuse the recovery. The tests above
    save at most one account each, so only this one can see that.
    """
    inactive_admin = make_user(role=Role.ADMIN, is_active=False)
    doctor = make_user(email="doctor@example.com", role=Role.DOCTOR)

    create_user(db_session, inactive_admin)
    create_user(db_session, doctor)
    db_session.flush()

    assert exists_active_admin(db_session) is False


def test_an_added_user_can_be_found_by_id(db_session: Session) -> None:
    """A saved user is returned by an ID lookup, and not the other saved user.

    The decoy is added first, so a lookup that ignored the ID and returned
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

    found_user = get_user_by_id(db_session, user.id)

    assert found_user is not None
    assert found_user.id == user.id


def test_an_unknown_id_finds_no_user(db_session: Session) -> None:
    """An ID that no user has returns None, even with users in the table.

    With rows to return, a lookup that ignored the ID and returned any user
    would fail here, whatever order the rows come in; the decoy saved
    first matters only to the test above, where the ID does match a user.
    """
    user = make_user()
    decoy_user = make_user(email="other@example.com")

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    assert get_user_by_id(db_session, uuid.uuid4()) is None


def test_a_locked_lookup_finds_the_user_by_id(db_session: Session) -> None:
    """The locking lookup returns the user with the ID, not the decoy saved first.

    The lookup queries the database whatever the session holds, and the
    session is emptied first, so the user comes back as a new object built
    from the stored row. The lock itself is tested in
    ``tests/test_auth_concurrency.py``, where a second connection can wait
    for it.
    """
    decoy_user = make_user(email="other@example.com")
    user = make_user()

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    found_user = get_user_by_id_for_update(db_session, user.id)

    assert found_user is not None
    assert found_user.id == user.id


def test_a_locked_lookup_of_an_unknown_id_finds_no_user(db_session: Session) -> None:
    """An ID that no user has returns None from the locking lookup too."""
    db_session.add(make_user())
    db_session.flush()
    db_session.expunge_all()

    assert get_user_by_id_for_update(db_session, uuid.uuid4()) is None


def test_a_locked_lookup_reads_the_user_as_the_database_holds_it_now(db_session: Session) -> None:
    """The locking lookup replaces a copy the session holds with the stored row.

    The name changes in the database through plain SQL, which leaves the
    session's copy as it was. The ordinary lookup returns that stale copy
    from memory, which shows the setup works; the locking lookup reads the
    row again and updates the same object, so a caller that waited for the
    lock sees what the transaction it waited for committed, such as a new
    password hash.
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

    found_user = get_user_by_id_for_update(db_session, user.id)

    assert found_user is user
    assert user.full_name == "New Name"
