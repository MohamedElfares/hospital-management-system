import uuid

import pytest
from factories import make_user
from factories import make_user_create
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.core.permissions import Role
from app.core.security import verify_password
from app.modules.users import repository
from app.modules.users.models import User
from app.modules.users.service import create_first_admin
from app.modules.users.service import create_user
from app.modules.users.service import get_user_by_email
from app.modules.users.service import get_user_by_id

EMAIL = "test@example.com"
PASSWORD = "Password@1331"


def test_create_user_saves_the_given_details(db_session: Session) -> None:
    """The saved row has the email, name, and role from the input."""
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

    The column's database default is true, so the "no change" case is the
    one that proves the value is really passed through.
    """
    data = make_user_create()
    user = create_user(db_session, data, must_change_password=must_change_password)

    db_session.expire_all()
    saved = db_session.get(User, user.id)

    assert saved is not None
    assert saved.must_change_password is must_change_password


def test_create_user_stores_a_hash_that_verifies_not_the_password(db_session: Session) -> None:
    """The stored password is an Argon2id hash that verifies, never the password itself."""
    data = make_user_create(password=PASSWORD)
    user = create_user(db_session, data, must_change_password=False)

    db_session.expire_all()
    saved = db_session.get(User, user.id)

    assert saved is not None
    assert saved.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, saved.password_hash)


def test_create_user_rejects_an_email_that_is_taken(db_session: Session) -> None:
    """A second account with the same email is refused, and only the first remains."""
    data = make_user_create()
    create_user(db_session, data, must_change_password=False)

    with pytest.raises(ConflictError) as exc_info:
        create_user(db_session, data, must_change_password=False)

    assert exc_info.value.message == "A user with this email already exists."
    count = db_session.scalar(
        select(func.count()).select_from(User).where(User.email == data.email)
    )
    assert count == 1


def test_a_duplicate_caught_by_the_database_becomes_a_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate that slips past the email check still becomes a ConflictError.

    ``get_by_email`` is replaced to miss the existing user, as happens when
    two requests check at the same moment. The database's unique constraint
    then rejects the insert, and the service must turn that into the same
    conflict, not an ``IntegrityError``. The existing user is committed, as
    an earlier request would have done, so the service's rollback can't
    remove it.
    """
    email = "test.new@example.com"

    existing_user = make_user(email=email)
    db_session.add(existing_user)
    db_session.commit()

    monkeypatch.setattr(
        repository,
        "get_by_email",
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
    """On an empty table the first Admin is active and keeps its chosen password.

    The person typed this password, so there is no temporary password to
    replace.
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
    """With an active Admin present, the command refuses and names that rule.

    The new input uses a different email, so the refusal can only come
    from the active-Admin check.
    """
    existing_admin = make_user(role=Role.ADMIN)
    db_session.add(existing_admin)
    db_session.flush()

    # Service input: Pydantic schema.
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
    """With only a deactivated Admin, a new Admin can be created to recover access."""
    # Existing database row: ORM model.
    inactive_admin = make_user(role=Role.ADMIN, is_active=False)
    db_session.add(inactive_admin)
    db_session.flush()

    # Service input: Pydantic schema.
    data = make_user_create(role=Role.ADMIN)

    # No exception: with no active Admin, recovery is allowed.
    result = create_first_admin(db_session, data)

    assert result.role is Role.ADMIN


def test_create_first_admin_always_creates_an_admin(db_session: Session) -> None:
    """Input asking for a Doctor still creates an Admin: the role is forced."""
    data = make_user_create(role=Role.DOCTOR)
    admin = create_first_admin(db_session, data)

    assert admin.role is Role.ADMIN


def test_get_user_by_email_finds_an_existing_user(db_session: Session) -> None:
    """An email that belongs to a saved user returns that user."""
    user = make_user()

    db_session.add(user)
    db_session.flush()

    result = get_user_by_email(db_session, user.email)

    assert result is user


def test_get_user_by_email_ignores_case_and_surrounding_spaces(db_session: Session) -> None:
    """A differently cased email with spaces around it still finds the user.

    Sign-in passes the raw form value, so the lookup must strip and
    lowercase it to match the lowercase email in the table.
    """
    user = make_user(email=EMAIL)

    db_session.add(user)
    db_session.flush()

    result = get_user_by_email(db_session, " Test@examPle.COM  ")

    assert result is user


def test_get_user_by_email_returns_none_for_an_unknown_email(db_session: Session) -> None:
    """An email that matches no user returns None, not an error.

    Another user exists, so None means "no match" rather than "empty
    table". Sign-in relies on None to take the dummy-hash path.
    """
    user = make_user(email=EMAIL)

    db_session.add(user)
    db_session.flush()

    result = get_user_by_email(db_session, "new.user@example.com")

    assert result is None


def test_get_user_by_email_returns_inactive_users_too(db_session: Session) -> None:
    """A deactivated user is still returned.

    Sign-in checks the password before ``is_active``, so the lookup must not
    hide inactive accounts; filtering them here would bypass that order.
    """
    user = make_user(is_active=False)

    db_session.add(user)
    db_session.flush()

    result = get_user_by_email(db_session, user.email)

    assert result is user


def test_get_user_by_id_finds_an_existing_user(db_session: Session) -> None:
    """A saved user is found by id through the service, not the decoy beside it.

    The decoy is added first so a lookup that ignored the id would return
    it, and the session is emptied so the result comes from the database.
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


def test_get_user_by_id_returns_none_for_an_unknown_id(db_session: Session) -> None:
    """An id that no user has returns None, even with users in the table."""
    user = make_user()
    decoy_user = make_user(email="other@example.com")

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()
    db_session.expunge_all()

    assert get_user_by_id(db_session, uuid.uuid4()) is None


def test_get_user_by_id_returns_inactive_users_too(db_session: Session) -> None:
    """A deactivated user is still found by id, with the flag read as stored.

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

    result = get_user_by_id(db_session, user.id)

    assert result is not None
    assert result.id == user.id
    assert result.is_active is False
