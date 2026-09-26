from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.modules.users.models import User

FAKE_PASSWORD_HASH = "$2a$12$xmwWaOMD74tVfixmTpxpWe7oZiybi9crvSu0lbrbe9NXCxX8CS1nq"


def make_user(**overrides: object) -> User:
    """Build an unsaved user with valid values, replacing any given fields.

    Each test changes only the field it is about, so a failure points at
    that field and not at unrelated setup. The user is not added to a
    session: the test adds and flushes it itself, which keeps the step that
    should fail visible inside the test.

    Args:
        **overrides: Column values that replace the defaults, such as
            ``email="Test@example.com"`` or ``role=None``.

    Returns:
        A new ``User`` that has not been added to any session.
    """
    values: dict[str, Any] = {
        "email": "test@example.com",
        "password_hash": FAKE_PASSWORD_HASH,
        "full_name": "Test User",
        "role": Role.ADMIN,
    }

    values.update(overrides)
    return User(**values)


def test_a_new_user_gets_the_default_flags(db_session: Session) -> None:
    """A user saved with only the required columns gets the safe defaults.

    The account is active, must change its password, is not demo data, and
    has never signed in. The values are read back from the database with
    ``refresh``, so the test checks the table's server defaults rather than
    anything set in Python.
    """
    user = make_user()

    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)

    assert user.is_active is True
    assert user.must_change_password is True
    assert user.is_demo is False
    assert user.last_login_at is None


def test_a_new_user_gets_timezone_aware_timestamps(db_session: Session) -> None:
    """The database sets ``created_at`` and ``updated_at`` with a timezone.

    Both come from ``now()`` on a ``TIMESTAMPTZ`` column, so they must come
    back as aware datetimes. The test does not check that ``updated_at``
    changes on update: ``now()`` is fixed for the whole transaction, and
    every test runs inside one transaction.
    """
    user = make_user()

    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)

    assert user.updated_at is not None
    assert user.updated_at.tzinfo is not None
    assert user.created_at is not None
    assert user.created_at.tzinfo is not None


def test_two_users_cannot_share_an_email(db_session: Session) -> None:
    """A second user with the same email is rejected by ``uq_users_email``."""
    first_user = make_user()
    second_user = make_user()

    db_session.add(first_user)
    db_session.flush()

    db_session.add(second_user)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert exc_info.value.orig.diag.constraint_name == "uq_users_email"


def test_an_email_with_capitals_is_rejected(db_session: Session) -> None:
    """An email with capital letters is rejected by the lowercase CHECK.

    The service lowercases emails, but this write goes through the ORM
    directly, as a seed script or a bug could. The database still refuses
    it.
    """
    user = make_user(email="Test@example.com")

    db_session.add(user)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert exc_info.value.orig.diag.constraint_name == "ck_users_email_lowercase"


def test_a_case_only_duplicate_email_is_rejected(db_session: Session) -> None:
    """An email that differs from an existing one only in case is rejected.

    The unique constraint alone would accept ``TEST@example.com`` next to
    ``test@example.com``. The lowercase CHECK rejects it first, which makes
    uniqueness effectively case-insensitive.
    """
    first_user = make_user(email="test@example.com")
    second_user = make_user(email="TEST@example.com")

    db_session.add(first_user)
    db_session.flush()

    db_session.add(second_user)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert exc_info.value.orig.diag.constraint_name == "ck_users_email_lowercase"


def test_an_unknown_role_is_rejected_before_sql(db_session: Session) -> None:
    """A role string that isn't a ``Role`` value fails in Python.

    ``validate_strings=True`` on the column type raises ``LookupError`` while
    SQLAlchemy prepares the parameters, which it wraps in ``StatementError``.
    No SQL reaches the database.
    """
    user = make_user(role="superuser")

    db_session.add(user)
    with pytest.raises(StatementError) as exc_info:
        db_session.flush()

    assert isinstance(exc_info.value.orig, LookupError)


def test_the_database_rejects_an_unknown_role(db_session: Session) -> None:
    """Raw SQL with an unknown role is rejected by ``ck_users_role``.

    Raw SQL skips the ORM's check, so this proves the database protects the
    column on its own. The ``id`` is generated in SQL because the model's
    UUID default runs only in Python; without it the insert would fail on
    the NULL ``id`` before reaching the role CHECK.
    """
    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(
            text("""
                    INSERT INTO users (id, email, password_hash, full_name, role)
                    VALUES (gen_random_uuid(), :email, :password_hash, :full_name, :role)
                """),
            {
                "email": "test@example.com",
                "password_hash": FAKE_PASSWORD_HASH,
                "full_name": "Test User",
                "role": "superuser",
            },
        )

    assert exc_info.value.orig.diag.constraint_name == "ck_users_role"


@pytest.mark.parametrize("column", ["email", "password_hash", "full_name", "role"])
def test_required_columns_cannot_be_null(db_session: Session, column: str) -> None:
    """Saving a user with a required column set to None is rejected.

    The error must name the same column, so a case can't pass because a
    different column was missing.
    """
    user = make_user(**{column: None})
    db_session.add(user)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert exc_info.value.orig.diag.column_name == column


def test_the_role_reads_back_as_a_role_member(db_session: Session) -> None:
    """A role loaded from the database is a ``Role`` member, not a string.

    The check uses ``is``, because a ``StrEnum`` member also equals its
    plain string, so ``==`` would pass even if a string came back.
    """
    user = make_user(role=Role.DOCTOR)
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)

    assert user.role is Role.DOCTOR


def test_the_role_is_stored_as_its_value(db_session: Session) -> None:
    """The role column stores the member's value ``"doctor"``, not its name.

    The row is read with raw SQL, so the ORM can't convert the result, and
    the test sees exactly what PostgreSQL stored.
    """
    user = make_user(role=Role.DOCTOR)
    db_session.add(user)
    db_session.flush()

    role = db_session.execute(
        text("SELECT role FROM users WHERE id = :user_id"), {"user_id": user.id}
    ).scalar_one()

    assert role == "doctor"
