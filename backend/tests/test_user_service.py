"""Tests for the users service: creating accounts and finding them.

The tests call the service's functions directly with ``db_session``, the
test's own session, with no request or command around them, and read the
results back in the same transaction. ``create_user`` saves the email,
name, role, and must-change flag it is given, stores an Argon2id hash that
verifies rather than the password, and turns a taken email into a
``ConflictError``: its own check finds the usual duplicate before the
password is hashed, and the database's unique constraint catches one that
slips past the check. ``create_first_admin`` creates an active Admin who
isn't asked to change the password they chose, forces the role to Admin,
and refuses while an active Admin exists, but not when every Admin is
deactivated. ``get_user_by_email`` finds an account however its address
was typed, through the ``Email`` rule that ``UserCreate`` stored it with,
and returns None without a query for text that isn't an address;
``get_user_by_id`` and ``get_user_by_id_for_update`` find an account by
its ID. Every lookup returns deactivated accounts too, because what
deactivation means is each caller's decision.

Work a service flushed stays visible in the test's session whether or not
the service committed it, so these tests can't see a missing ``commit()``;
the ``create-admin`` tests in ``tests/test_cli.py`` can, because
``get_test_db`` rolls back what the command didn't commit. The queries
underneath are tested in ``tests/test_user_repository.py``, the lock that
``get_user_by_id_for_update`` takes in ``tests/test_auth_concurrency.py``,
and the ``Email`` rule itself in ``tests/test_user_schemas.py``.
"""

# Unicode normalization; builds the decomposed form of an accented email.
import unicodedata

# Random UUIDs; an ID that no saved account has.
import uuid

# Test framework: raises, parametrize, and monkeypatch to replace a repository function.
import pytest

# Builds an unsaved User, the account a test saves before it looks it up or collides with it.
from factories import make_user

# Builds validated UserCreate input, as a person would submit it.
from factories import make_user_create

# SQL's COUNT; counts the accounts that hold an email after a refusal.
from sqlalchemy import func

# Builds the counting query.
from sqlalchemy import select

# Type of the db_session fixture.
from sqlalchemy.orm import Session

# What the service raises when a rule refuses an account; its message is checked.
from app.core.errors import ConflictError

# The role enum; sets the input's role and checks the saved one.
from app.core.permissions import Role

# Checks that the stored hash matches the password that was typed.
from app.core.security import verify_password

# The users repository as a module, so a test can replace its email lookup.
from app.modules.users import repository

# The users table's ORM model; saved rows are read back and counted through it.
from app.modules.users.models import User

# The use case behind create-admin, under test.
from app.modules.users.service import create_first_admin

# The use case that saves a new account, under test.
from app.modules.users.service import create_user

# The email lookup that sign-in uses, under test.
from app.modules.users.service import get_user_by_email

# The ID lookup that loads each request's user, under test.
from app.modules.users.service import get_user_by_id

# The locking ID lookup that auth takes before it changes a user's sessions, under test.
from app.modules.users.service import get_user_by_id_for_update

# make_user's default email, written out where a lookup test types a different text.
EMAIL = "test@example.com"

# Passes the 15-character password rule; the stored hash must verify against it.
PASSWORD = "Correct-Password-1"


def test_create_user_saves_the_given_details(db_session: Session) -> None:
    """The saved row holds the email, full name, and role of the input.

    The session is expired before the row is read back, so the values come
    from the database rather than from the object ``create_user`` returned.
    The input asks for a Receptionist, not the factory's default Doctor, so
    the role can only have come from the input. The must-change flag and
    the password hash have tests of their own.
    """
    data = make_user_create(role=Role.RECEPTIONIST)
    user = create_user(db_session, data, must_change_password=False)

    db_session.expire_all()
    saved = db_session.get(User, user.id)

    assert saved is not None
    assert saved.id is not None
    assert saved.email == data.email
    assert saved.full_name == data.full_name
    assert saved.role is Role.RECEPTIONIST


@pytest.mark.parametrize(
    "must_change_password",
    [pytest.param(True, id="must change"), pytest.param(False, id="no change")],
)
def test_create_user_stores_the_must_change_password_flag(
    db_session: Session,
    must_change_password: bool,
) -> None:
    """The saved row keeps the ``must_change_password`` value passed in.

    The column's server default is true, so the "no change" case is the one
    that proves the value is passed through rather than left to the
    default, and the "must change" case, the value staff accounts will get
    (IAM-5), proves it isn't always written as false.
    """
    data = make_user_create()
    user = create_user(db_session, data, must_change_password=must_change_password)

    db_session.expire_all()
    saved = db_session.get(User, user.id)

    assert saved is not None
    assert saved.must_change_password is must_change_password


def test_create_user_stores_a_hash_that_verifies_not_the_password(db_session: Session) -> None:
    """The stored password is an Argon2id hash that verifies, never the password itself.

    A stored plain password fails the prefix check, and a hash of anything
    other than the typed password fails the verification. The hash's
    settings are pinned in ``tests/test_security.py``.
    """
    data = make_user_create(password=PASSWORD)
    user = create_user(db_session, data, must_change_password=False)

    db_session.expire_all()
    saved = db_session.get(User, user.id)

    assert saved is not None
    assert saved.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, saved.password_hash)


def test_create_user_rejects_a_taken_email_before_hashing_the_password(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A taken email is refused before the password is hashed, and only the first account remains.

    The same input is submitted twice: the first ``create_user`` commits,
    and the second is refused with the duplicate message, and saves
    nothing. The service checks the email before it hashes the password, so
    a duplicate never costs an Argon2 hash. The unique constraint behind the
    check would refuse it with the same message, as
    ``test_a_duplicate_caught_by_the_database_becomes_a_conflict`` shows,
    but only after the hashing, so once the first account is saved,
    ``hash_password`` is replaced, where the service looks it up, with a spy
    that records each call: an empty record shows that the check came first.
    """
    data = make_user_create()
    create_user(db_session, data, must_change_password=False)

    hashed_passwords: list[str] = []

    def record_hashing(password: str) -> str:
        """Record the password the service would hash, instead of hashing it.

        Args:
            password: The plain password the service passed in.

        Returns:
            A stand-in for the hash, so that code which hashes before the
            check still reaches the insert, which the constraint refuses.
        """
        hashed_passwords.append(password)
        return "not-a-real-hash"

    monkeypatch.setattr("app.modules.users.service.hash_password", record_hashing)

    with pytest.raises(ConflictError) as exc_info:
        create_user(db_session, data, must_change_password=False)

    assert exc_info.value.message == "A user with this email already exists."
    assert hashed_passwords == []
    count = db_session.scalar(
        select(func.count()).select_from(User).where(User.email == data.email)
    )
    assert count == 1


def test_a_duplicate_caught_by_the_database_becomes_a_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate that slips past the email check still becomes a ConflictError.

    ``repository.get_user_by_email`` is replaced to miss the existing user,
    as happens when two requests check at the same moment. The database's
    unique constraint then rejects the insert, and the service must turn
    that into the same conflict, not an ``IntegrityError``. The existing
    user is committed, as an earlier request would have done, so the
    service's rollback can't remove it. The count afterwards runs on the
    same session, so it also shows that the rollback left the session
    usable: without it, the query fails with ``PendingRollbackError``.
    """
    email = "test.new@example.com"

    existing_user = make_user(email=email)
    db_session.add(existing_user)
    db_session.commit()

    monkeypatch.setattr(
        repository,
        "get_user_by_email",
        lambda session, email: None,
    )

    with pytest.raises(ConflictError) as exc_info:
        create_user(
            db_session,
            make_user_create(email=email),
            must_change_password=False,
        )

    assert exc_info.value.message == "A user with this email already exists."

    count = db_session.scalar(select(func.count()).select_from(User).where(User.email == email))
    assert count == 1


def test_the_first_admin_is_an_active_admin_without_a_forced_password_change(
    db_session: Session,
) -> None:
    """On an empty table, the first Admin is active and needn't change its password.

    The person running ``create-admin`` typed this password themselves, so
    there is no temporary password to replace. The input already asks for
    an Admin; ``test_create_first_admin_always_creates_an_admin`` shows
    that the role is forced.
    """
    data = make_user_create(role=Role.ADMIN)
    admin = create_first_admin(db_session, data)

    db_session.expire_all()
    saved = db_session.get(User, admin.id)

    assert saved is not None
    assert saved.role is Role.ADMIN
    assert saved.is_active is True
    assert saved.must_change_password is False


def test_create_first_admin_refuses_when_an_active_admin_exists(
    db_session: Session,
) -> None:
    """With an active Admin saved, ``create_first_admin`` refuses with the rule's message.

    The saved Admin, built by ``make_user``, is active by the column's
    default, and the input, built by ``make_user_create``, has another
    email, so the refusal can only come from the active-Admin check, not
    from a taken email. The message tells the person where further Admins
    come from.
    """
    existing_admin = make_user(role=Role.ADMIN)
    db_session.add(existing_admin)
    db_session.flush()

    data = make_user_create(role=Role.ADMIN)

    with pytest.raises(ConflictError) as exc_info:
        create_first_admin(db_session, data)

    assert (
        exc_info.value.message
        == "An active Admin already exists. Create more Admins through the API."
    )


def test_create_first_admin_recovers_access_when_every_admin_is_inactive(
    db_session: Session,
) -> None:
    """With only a deactivated Admin saved, a new Admin is created, so access can be recovered.

    Besides a fresh database, this is the case the command exists for:
    once every Admin is deactivated, nobody can create one through the
    API. The saved Admin, built by ``make_user``, and the input, built by
    ``make_user_create``, have different emails, so only the active-Admin
    check could refuse, and it must ignore deactivated accounts.
    """
    inactive_admin = make_user(role=Role.ADMIN, is_active=False)
    db_session.add(inactive_admin)
    db_session.flush()

    data = make_user_create(role=Role.ADMIN)

    # No pytest.raises: a deactivated Admin must not block the command.
    admin = create_first_admin(db_session, data)

    assert admin.role is Role.ADMIN


def test_create_first_admin_always_creates_an_admin(db_session: Session) -> None:
    """Input asking for a Doctor still creates an Admin: the role is forced.

    ``create-admin`` always asks for an Admin, but the service doesn't rely
    on its caller for that. Doctor is ``make_user_create``'s default role,
    written out so the test reads on its own.
    """
    data = make_user_create(role=Role.DOCTOR)
    admin = create_first_admin(db_session, data)

    assert admin.role is Role.ADMIN


def test_get_user_by_email_finds_an_existing_user(db_session: Session) -> None:
    """An email that belongs to a saved user returns that user.

    The lookup returns the very object the session holds, because the row
    a query finds maps to the session's existing copy of it.
    """
    user = make_user()

    db_session.add(user)
    db_session.flush()

    found_user = get_user_by_email(db_session, user.email)

    assert found_user is user


def test_get_user_by_email_ignores_case_and_surrounding_spaces(db_session: Session) -> None:
    """A differently cased email with spaces around it still finds the user.

    Sign-in passes the raw form value, so the lookup must strip and
    lowercase it to match the lowercase email in the table. It puts the
    text through the ``Email`` rule, which does both, as it does before
    ``UserCreate`` stores an address.
    """
    user = make_user(email=EMAIL)

    db_session.add(user)
    db_session.flush()

    found_user = get_user_by_email(db_session, " Test@examPle.COM  ")

    assert found_user is user


@pytest.mark.parametrize(
    "typed_email",
    [
        pytest.param("Test@ＥＸＡＭＰＬＥ.com", id="full-width-domain"),
        pytest.param(unicodedata.normalize("NFD", "José@example.com"), id="decomposed-accent"),
    ],
)
def test_get_user_by_email_finds_an_address_that_user_create_rewrote(
    db_session: Session,
    typed_email: str,
) -> None:
    """Text that ``UserCreate`` rewrote before storing still finds its account.

    email-validator turns full-width letters in the domain into ASCII and a
    decomposed accent into a single character, so ``UserCreate`` stores
    ``test@example.com`` for the first case, and for the second an address
    whose accented e is the one code point U+00E9. The first assertion
    shows the stored form differs from the text merely stripped and
    lowercased, so only the shared ``Email`` rule can make the lookup match.
    """
    stored_email = make_user_create(email=typed_email).email
    user = make_user(email=stored_email)

    db_session.add(user)
    db_session.flush()

    assert stored_email != typed_email.strip().lower()
    assert get_user_by_email(db_session, typed_email) is user


@pytest.mark.parametrize(
    "typed_text",
    [
        pytest.param("test\x00@example.com", id="nul-character"),
        pytest.param("test", id="no-at-sign"),
        pytest.param("", id="empty"),
    ],
)
def test_get_user_by_email_returns_none_for_text_that_is_not_an_address(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    typed_text: str,
) -> None:
    """Text that isn't an address returns None, and the database is never asked.

    No account can have such an email, because every stored one passed the
    same rule. The NUL case is the one that matters most: PostgreSQL
    refuses that character, so a query would fail with an error instead of
    finding nobody. The repository's lookup is replaced with a spy that
    records every call, so an empty record proves the service never asked
    it.
    """
    lookups: list[str] = []

    def record_lookup(session: Session, email: str) -> None:
        """Record the email the service asked for, instead of querying.

        Args:
            session: The test's session, unused.
            email: The normalized email the service would have looked up.

        Returns:
            None, the answer for an email that no account has.
        """
        lookups.append(email)

    monkeypatch.setattr(repository, "get_user_by_email", record_lookup)

    assert get_user_by_email(db_session, typed_text) is None
    assert lookups == []


def test_get_user_by_email_returns_none_for_an_unknown_email(db_session: Session) -> None:
    """An email that matches no user returns None, not an error.

    Another user exists, so None means "no match" rather than "empty
    table". Sign-in relies on None to take the dummy-hash path.
    """
    user = make_user(email=EMAIL)

    db_session.add(user)
    db_session.flush()

    found_user = get_user_by_email(db_session, "new.user@example.com")

    assert found_user is None


def test_get_user_by_email_returns_inactive_users_too(db_session: Session) -> None:
    """A deactivated user is still returned.

    What deactivation means is the caller's decision. Sign-in checks the
    password before it looks at ``is_active``, so it needs the account
    either way; a lookup that hid deactivated accounts would make that
    decision for every caller, ahead of the password check.
    """
    user = make_user(is_active=False)

    db_session.add(user)
    db_session.flush()

    found_user = get_user_by_email(db_session, user.email)

    assert found_user is user


def test_get_user_by_id_finds_an_existing_user(db_session: Session) -> None:
    """A saved user is found by ID through the service, not the decoy saved before it.

    The decoy is added first, so a lookup that ignored the ID would find
    it first, and the session is emptied, so the user is read from the
    database rather than from the session's memory.
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


def test_get_user_by_id_returns_none_for_an_unknown_id(db_session: Session) -> None:
    """An ID that no user has returns None, even with users in the table.

    A random UUID stands for an ID that no account has, and with two
    accounts saved, None can't come from an empty table.
    """
    user = make_user()
    decoy_user = make_user(email="other@example.com")

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    assert get_user_by_id(db_session, uuid.uuid4()) is None


def test_get_user_by_id_returns_inactive_users_too(db_session: Session) -> None:
    """A deactivated user is still found by ID, with the flag read as stored.

    The service leaves deactivation to its callers: auth rejects inactive
    users, but staff administration must still find them to reactivate
    them. The ``is_active`` check proves the inactive row itself came back.
    """
    decoy_user = make_user(email="other@example.com")
    user = make_user(is_active=False)

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    found_user = get_user_by_id(db_session, user.id)

    assert found_user is not None
    assert found_user.id == user.id
    assert found_user.is_active is False


def test_get_user_by_id_for_update_finds_an_existing_user(db_session: Session) -> None:
    """The service's locking lookup finds a saved user by ID, not the decoy saved before it.

    The decoy is added first, and the session is emptied, so the user is
    read from the database and belongs to the ID that was asked for. The
    lock itself is tested in ``tests/test_auth_concurrency.py``, where a
    second connection waits for it.
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


def test_get_user_by_id_for_update_returns_inactive_users_too(db_session: Session) -> None:
    """A deactivated user is still found by the locking lookup, flag and all.

    Sign-in, refresh, and the password change each lock the account and
    then check ``is_active`` on the row they locked, so the lookup must
    return the inactive row and leave the refusal to its caller.
    """
    user = make_user(is_active=False)

    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    found_user = get_user_by_id_for_update(db_session, user.id)

    assert found_user is not None
    assert found_user.is_active is False
