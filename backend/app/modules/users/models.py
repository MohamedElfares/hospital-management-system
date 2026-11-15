"""ORM model for user accounts, and the enum column type it uses.

A user is anyone who can sign in: staff in every role and, from Phase 4,
patients with portal access. The table enforces the rules that must hold
even under concurrent requests or writes that bypass the service: emails are
unique and stored lowercase, and roles are limited to ``Role`` values. Users
are deactivated, never deleted.
"""

# Python type of the last_login_at attribute.
from datetime import datetime

# Python base class for string enums; the type accepted by string_enum.
from enum import StrEnum

# Column type for the true/false account flags.
from sqlalchemy import Boolean

# Table-level CHECK constraint; keeps stored emails lowercase.
from sqlalchemy import CheckConstraint

# Column type that maps to TIMESTAMPTZ when timezone=True; used for last_login_at.
from sqlalchemy import DateTime

# SQLAlchemy's enum column type; string_enum configures it as a checked VARCHAR.
from sqlalchemy import Enum

# Declares the composite index on role and is_active.
from sqlalchemy import Index

# VARCHAR column type with a maximum length.
from sqlalchemy import String

# SQL FALSE literal; database default for is_demo.
from sqlalchemy import false

# SQL TRUE literal; database default for is_active and must_change_password.
from sqlalchemy import true

# Annotation that declares a model attribute's Python type and nullability.
from sqlalchemy.orm import Mapped

# Defines a column's database type, defaults, and options.
from sqlalchemy.orm import mapped_column

# The role enum stored in users.role.
from app.core.permissions import Role

# Declarative base whose metadata registers the users table.
from app.db.base import Base

# Adds created_at and updated_at set by the database clock.
from app.db.base import TimestampMixin

# Adds the UUID primary key named id.
from app.db.base import UUIDPrimaryKeyMixin


def string_enum(enum_cls: type[StrEnum], *, name: str, length: int = 32) -> Enum:
    """Build a column type that stores a ``StrEnum`` as a checked VARCHAR.

    Plan §7 stores enums as strings, not PostgreSQL enum types, because
    changing a native enum needs awkward migrations. The column stores each
    member's value (``"admin"``), not its name (``"ADMIN"``), so the
    database, the API, and SQL filters all use the same string. A named
    CHECK constraint makes PostgreSQL reject any value that isn't a member,
    even when a write bypasses the ORM. SQLAlchemy also checks plain strings
    while it prepares the parameters, so a typo fails in Python, as a
    ``StatementError`` wrapping ``LookupError``, before the statement
    reaches the database.

    The length is fixed rather than taken from the longest current value, so
    adding a member later only changes the CHECK constraint, not the column
    width.

    Args:
        enum_cls: The enum class to store, such as ``Role``.
        name: Name of the CHECK constraint. The naming convention turns
            ``"role"`` on the ``users`` table into ``ck_users_role``. It must
            be explicit because the ``ck`` convention uses the constraint name.
        length: Maximum length of the stored value. Every member's value
            must fit.

    Returns:
        A SQLAlchemy ``Enum`` type to pass to ``mapped_column``.

    Example:
        ``role: Mapped[Role] = mapped_column(string_enum(Role, name="role"))``
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person who can sign in, with one role.

    There is no public sign-up (plan §3): the ``create-admin`` command
    creates the first Admin, Admins create any account, Managers create
    staff accounts for every role except Admin and Manager, and
    receptionists enable portal access for patients. Nullability comes from
    each ``Mapped`` annotation: ``X`` is NOT NULL and ``X | None`` allows
    NULL.

    The three flags have database defaults, so rows inserted outside the ORM
    still get safe values. ``must_change_password`` defaults to true because
    most accounts start with a temporary password that whoever created the
    account knows; if a code path forgets to set it, the user only has to
    choose a new password. ``create-admin`` sets it to false explicitly, and
    ``seed-demo`` will too (Milestone 1.7).

    Attributes:
        email: Sign-in name. Unique, and stored lowercase: ``UserCreate``
            lowercases it, and a CHECK constraint rejects anything else, so
            uniqueness is effectively case-insensitive.
        password_hash: Argon2 hash of the password. The plain password is
            never stored, logged, or returned.
        full_name: The person's name, returned by ``GET /auth/me``. The
            staff list (IAM-5) and the audit log (Milestone 1.3) will show
            it too.
        role: The user's only role. Route authorization will check the
            permissions it grants, never the role itself (plan §6, IAM-4).
            Queries may still filter on it, as ``create-admin``'s check for
            an active Admin does.
        is_active: False once the account is deactivated. An inactive user
            gets 401 on sign-in, on refresh, and on every authenticated
            request.
        must_change_password: True while the password is temporary. Until
            it is changed, every authenticated route except
            ``GET /auth/me``, ``POST /auth/logout``, and
            ``POST /auth/change-password`` returns 403
            ``PASSWORD_CHANGE_REQUIRED``.
        is_demo: Marks the accounts ``seed-demo`` creates, which will be
            protected from changes and replaced by ``seed-demo --reset``.
            Nothing sets or reads it before that command arrives in
            Milestone 1.7.
        last_login_at: When the user last signed in, in UTC. None if they
            never have.
    """

    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(string_enum(Role, name="role"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=true())
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default=false())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The composite index serves filters on role alone or on role with
    # is_active: create-admin's active-Admin check today, and the staff list
    # filters (IAM-5) later. Searching by name or email gets its own index
    # with the search query (IAM-5).
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        Index("ix_users_role_is_active", "role", "is_active"),
    )
