"""Builders for valid test objects, shared by the test files.

A factory returns an object that satisfies every rule, so each test changes
only the field it is about. Keeping the builders here means one place to
update when a model gains a required column. Test files import them
directly (``from factories import make_user``). That works because this
folder has no ``__init__.py``: in pytest's default import mode,
``prepend``, pytest puts such a folder at the front of ``sys.path`` before
it imports the tests in it.
"""

# Random hex values; a unique stand-in hash for each built refresh token.
import secrets

# Type of the user ID that every refresh token must reference.
import uuid

# UTC time zone; refresh token expiries are always in UTC.
from datetime import UTC

# Date and time type; now(UTC) is where a token's default expiry starts.
from datetime import datetime

# Adds the seven-day lifetime, the application's default, to the current time.
from datetime import timedelta

# Allows the defaults dict to hold values of different types.
from typing import Any

# Role enum; supplies each factory's default role.
from app.core.permissions import Role

# The ORM model make_refresh_token builds.
from app.modules.auth.models import RefreshToken

# The ORM model make_user builds.
from app.modules.users.models import User

# The input schema make_user_create builds and validates.
from app.modules.users.schemas import UserCreate

# A bcrypt hash, deliberately not Argon2. The pwdlib hasher in security.py
# reads only Argon2 hashes, so verify_password treats this value as an
# unknown format: it returns False for every password and logs a warning.
# A user built with it can never sign in, and the value is never a real
# secret.
FAKE_PASSWORD_HASH = "$2a$12$xmwWaOMD74tVfixmTpxpWe7oZiybi9crvSu0lbrbe9NXCxX8CS1nq"


def make_user(**overrides: object) -> User:
    """Build an unsaved user with valid values, replacing any given fields.

    Each test changes only the field it is about, so a failure points at
    that field and not at unrelated setup. The user is not added to a
    session: the test adds and flushes it itself, which keeps the step that
    should fail visible inside the test.

    The default user is an Admin, ``Test User``, whose email,
    ``test@example.com``, is the same on every call, so a test that saves
    two users gives one of them another email. Its password hash is
    ``FAKE_PASSWORD_HASH``, so it can't sign in;
    a test that signs in passes ``password_hash=hash_password(...)``. The
    database supplies ``is_active``, ``must_change_password``, and
    ``is_demo``, so they read ``None`` until the user is flushed, and then
    describe an active account, not a demo one, that must change its
    password at the next sign-in. A test that needs to get past the
    password-change gate sets ``must_change_password=False``.

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


def make_user_create(**overrides: object) -> UserCreate:
    """Build valid input for the users service, replacing any given fields.

    ``make_user`` stands for an account that is already saved; this builds
    what a person submits to create one, so it goes through ``UserCreate``'s
    validation like real input. The default email, ``new.user@example.com``,
    differs from ``make_user``'s, so an existing user and new input never
    collide unless a test sets the same email on purpose, and a
    ``ConflictError`` can't come from a duplicate email by accident. The
    default role is Doctor, so a test of ``create_first_admin`` that gets
    an Admin proves the role was forced rather than copied.

    Args:
        **overrides: Field values that replace the defaults. They are
            validated like real input.

    Returns:
        A validated ``UserCreate``.

    Raises:
        ValidationError: If an override breaks one of ``UserCreate``'s
            rules, as the same value would in real input.
    """
    values: dict[str, Any] = {
        "email": "new.user@example.com",
        "full_name": "test user",
        "password": "Correct-Password-1",
        "role": Role.DOCTOR,
    }

    values.update(overrides)

    return UserCreate(**values)


def make_refresh_token(user_id: uuid.UUID, **overrides: object) -> RefreshToken:
    """Build an unsaved refresh token for a user, replacing any given fields.

    The token is unrevoked, has no replacement, and expires seven days from
    now, the application's default lifetime. Its hash is 64 random hex
    characters, the shape of the SHA-256 hex digest ``hash_refresh_token``
    stores, and different on every call, so a test that builds several
    tokens never breaks the unique constraint by accident; a test that
    wants a duplicate passes the same ``token_hash`` twice. The user ID is
    required because the foreign key needs a saved user, which the test
    creates and flushes first.

    Args:
        user_id: ID of the user the token belongs to, given to the model
            as it is, so ``None`` tests the column's NOT NULL rule. A
            positional ID and a ``user_id`` override can't be combined:
            Python raises ``TypeError`` for the second value. A test that
            sets one column at a time, ``user_id`` included, therefore puts
            both in one dict, as in
            ``make_refresh_token(**{"user_id": user.id, column: None})``,
            where the later key wins when ``column`` is ``"user_id"``.
        **overrides: Column values that replace the defaults, such as
            ``token_hash=...`` or ``expires_at=None``.

    Returns:
        A new ``RefreshToken`` that has not been added to any session.
    """
    values: dict[str, Any] = {
        "user_id": user_id,
        "token_hash": secrets.token_hex(32),
        "expires_at": datetime.now(UTC) + timedelta(days=7),
    }

    values.update(overrides)

    return RefreshToken(**values)
