"""Tests for the users table: its defaults, its constraints, and its role column.

The tests save users built by ``make_user`` into the test database, whose
schema the migrations built, and read them back, through the ORM or, where
the point is what the database refuses or stores on its own, with raw SQL.
They cover the safe defaults a new account gets, timestamps that read back
timezone-aware, an email that is unique and stored lowercase, a role that
SQLAlchemy checks before any SQL is sent and the database checks again,
the four columns with no default refusing NULL, and a role stored as its
value that reads back as a ``Role`` member. Each refusal by the database
is checked by the constraint or column it names, so a test can't pass
because some other rule failed. What the users service does with these
rules, such as turning a taken email into a ``ConflictError``, is tested
in ``tests/test_user_service.py``.
"""

# PostgreSQL's error classes in the driver; each refusal is checked by its exact class.
import psycopg

# Test framework: raises, and parametrize over the required columns.
import pytest

# The bcrypt stand-in for a password hash, which the raw SQL insert stores.
from factories import FAKE_PASSWORD_HASH

# Builds a valid unsaved user; each test overrides only the field it is about.
from factories import make_user

# Raw SQL, for a write and a read that bypass the ORM's checks and conversions.
from sqlalchemy import text

# What a write the database refuses raises; its orig attribute holds the driver's error.
from sqlalchemy.exc import IntegrityError

# What SQLAlchemy raises when it can't prepare a statement's parameters.
from sqlalchemy.exc import StatementError

# Type of the db_session fixture.
from sqlalchemy.orm import Session

# The role enum; a stored member must come back as itself.
from app.core.permissions import Role


def test_a_new_user_gets_the_default_flags(db_session: Session) -> None:
    """A user saved with only the required columns gets the safe defaults.

    The account is active, must change its password, is not demo data, and
    has never signed in. ``make_user`` sets only the four columns with no
    default, and the model gives the flags no Python default, so their
    values come from the table's server defaults; ``refresh`` reads them
    back from the row. The must-change default matters most: an account
    created by a code path that forgets the flag must still replace its
    temporary password before any other route opens (plan §8.1).
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
    """``created_at`` and ``updated_at`` read back as timezone-aware datetimes.

    The database fills both with ``now()`` on insert. They are
    ``TIMESTAMPTZ`` columns, which hold an instant rather than a wall-clock
    time, so the driver returns them with a time zone, as plan §7 asks.
    The test doesn't check that an update moves ``updated_at``: ``now()``
    is the transaction's start time, and every test runs inside one
    transaction, so an update writes the same instant the insert did.
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
    """A second user with the same email is rejected by ``uq_users_email``.

    The email is the sign-in name, so two accounts sharing one would make
    sign-in ambiguous. The users service looks for a taken email first,
    but two requests can both pass that check at the same moment, and only
    the database's unique constraint holds then (plan §7).
    """
    first_user = make_user()
    second_user = make_user()

    db_session.add(first_user)
    db_session.flush()

    db_session.add(second_user)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    orig = exc_info.value.orig
    assert isinstance(orig, psycopg.errors.UniqueViolation)
    assert orig.diag.constraint_name == "uq_users_email"


def test_an_email_with_capitals_is_rejected(db_session: Session) -> None:
    """An email with capital letters is rejected by ``ck_users_email_lowercase``.

    ``UserCreate`` lowercases every email before the users service stores
    it, but this write goes through the ORM directly, as a seed script or a
    bug could. The database still refuses it, so every stored email is in
    the form sign-in looks up.
    """
    user = make_user(email="Test@example.com")

    db_session.add(user)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    orig = exc_info.value.orig
    assert isinstance(orig, psycopg.errors.CheckViolation)
    assert orig.diag.constraint_name == "ck_users_email_lowercase"


def test_a_case_only_duplicate_email_is_rejected(db_session: Session) -> None:
    """An email that differs from an existing one only in case is rejected.

    The unique constraint compares the exact text, so on its own it would
    accept ``TEST@example.com`` next to ``test@example.com``. The lowercase
    CHECK refuses the second address, so no two stored emails can differ
    only in case, and uniqueness is effectively case-insensitive.
    """
    first_user = make_user(email="test@example.com")
    second_user = make_user(email="TEST@example.com")

    db_session.add(first_user)
    db_session.flush()

    db_session.add(second_user)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    orig = exc_info.value.orig
    assert isinstance(orig, psycopg.errors.CheckViolation)
    assert orig.diag.constraint_name == "ck_users_email_lowercase"


def test_an_unknown_role_is_rejected_before_sql(db_session: Session) -> None:
    """A role string that isn't a ``Role`` value fails in Python, before the insert.

    ``validate_strings=True`` on the column type makes SQLAlchemy raise
    ``LookupError`` while it prepares the statement's parameters, wrapped in
    ``StatementError``, so the ``INSERT`` is never sent; the only statement
    that follows is the session's rollback. The test checks the wrapped
    error, because ``IntegrityError``, which a refusal by the database
    raises, is a ``StatementError`` too.
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
    the NULL ``id`` before reaching the role CHECK. Every other column is
    either given or filled by a database default, so the role is the only
    rule the row breaks.
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

    orig = exc_info.value.orig
    assert isinstance(orig, psycopg.errors.CheckViolation)
    assert orig.diag.constraint_name == "ck_users_role"


@pytest.mark.parametrize("column", ["email", "password_hash", "full_name", "role"])
def test_required_columns_cannot_be_null(db_session: Session, column: str) -> None:
    """Saving a user with a required column set to None is rejected.

    These are the four columns with no default. SQLAlchemy sends a ``None``
    in such a column as NULL, which the column's NOT NULL refuses, and the
    error must name the same column, so a case can't pass because a
    different column was missing. The three flags aren't listed: SQLAlchemy
    leaves a ``None`` flag out of the ``INSERT``, so the flag gets its
    server default instead.
    """
    user = make_user(**{column: None})
    db_session.add(user)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    orig = exc_info.value.orig
    assert isinstance(orig, psycopg.errors.NotNullViolation)
    assert orig.diag.column_name == column


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

    The value is the string the database's CHECK lists and the API sends,
    so SQL filters and responses spell a role one way. The row is read with
    raw SQL, so the ORM can't convert the result, and the test sees exactly
    what PostgreSQL stored.
    """
    user = make_user(role=Role.DOCTOR)
    db_session.add(user)
    db_session.flush()

    stored_role = db_session.execute(
        text("SELECT role FROM users WHERE id = :user_id"), {"user_id": user.id}
    ).scalar_one()

    assert stored_role == "doctor"
