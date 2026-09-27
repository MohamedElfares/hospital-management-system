"""Builders for valid test objects, shared by every test file.

A factory returns an object that satisfies every rule, so each test changes
only the field it is about. Keeping the builders here means one place to
update when a model gains a required column. Test files import them
directly (``from factories import make_user``), which works because pytest
puts this folder on the import path.
"""

# Allows the defaults dict to hold values of different types.
from typing import Any

# Default role for built users.
from app.core.permissions import Role

# The ORM model the factory builds.
from app.modules.users.models import User

# A bcrypt value, deliberately not Argon2id. verify_password rejects every
# format except Argon2id, so a user built with it can never sign in with
# any password, and the value is never a real secret.
FAKE_PASSWORD_HASH = "$2a$12$xmwWaOMD74tVfixmTpxpWe7oZiybi9crvSu0lbrbe9NXCxX8CS1nq"


def make_user(**overrides: object) -> User:
    """Build an unsaved user with valid values, replacing any given fields.

    Each test changes only the field it is about, so a failure points at
    that field and not at unrelated setup. The user is not added to a
    session: the test adds and flushes it itself, which keeps the step that
    should fail visible inside the test. The default user is an active
    Admin.

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
