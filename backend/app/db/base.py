"""Declarative base class and reusable column mixins for all models.

Every model inherits from ``Base``, so ``Base.metadata`` is the registry of
all tables that Alembic compares with the database. The mixins apply the
project-wide rules from the plan: UUID primary keys, and ``created_at`` and
``updated_at`` stored as timezone-aware timestamps set by the database
clock. This module does not import settings, so models can be imported
without a database or a ``.env`` file.

Example:
    ``class Patient(UUIDPrimaryKeyMixin, TimestampMixin, Base): ...``
"""

# Standard-library UUID type and the uuid4() generator used for primary keys.
import uuid

# Python type of the timestamp attributes.
from datetime import datetime

# Allows mapper argument values of any type in __mapper_args__.
from typing import Any

# Marks __mapper_args__ as a class-level setting, not an instance attribute or column.
from typing import ClassVar

# Column type that maps to PostgreSQL TIMESTAMPTZ when timezone=True.
from sqlalchemy import DateTime

# Table registry; carries the constraint naming convention.
from sqlalchemy import MetaData

# Generic UUID column type; native UUID on PostgreSQL.
from sqlalchemy import Uuid

# Builds SQL function calls; func.now() lets the database set timestamps.
from sqlalchemy import func

# Modern typed base class for ORM models.
from sqlalchemy.orm import DeclarativeBase

# Annotation that declares a model attribute's Python type.
from sqlalchemy.orm import Mapped

# Defines a column's database type, defaults, and options.
from sqlalchemy.orm import mapped_column

# Deterministic names for indexes and constraints. Without them PostgreSQL
# invents names, and Alembic can't reliably alter or drop them later.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Parent class of every ORM model.

    Its ``metadata`` collects every table declared by a subclass and applies
    ``NAMING_CONVENTION`` to their constraints, so a unique constraint on
    ``users.email`` is always named ``uq_users_email``. Because the ``ck``
    convention uses ``%(constraint_name)s``, every ``CheckConstraint`` must
    be given an explicit ``name``. A model's table appears in the metadata
    only after its module is imported, so Alembic's ``env.py`` must import
    every models module.

    Attributes:
        metadata: Registry of all mapped tables, with the project's
            constraint naming convention.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Adds a UUID primary key named ``id``.

    The UUID is generated in Python (``uuid.uuid4``) when the object is
    flushed, not by the database, so a service can use the new ID in the same
    transaction, for example in the audit entry. Random UUIDs also keep
    record IDs unguessable, which supports the rule that out-of-scope records
    return 404. ``sort_order`` places the column first in the table.

    Attributes:
        id: Primary key, stored as a native PostgreSQL ``UUID``.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        sort_order=-10,
    )


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` timestamps set by the database.

    Both columns are ``TIMESTAMPTZ``, so values are stored as UTC instants
    and returned as timezone-aware datetimes. PostgreSQL fills both on
    insert (``server_default``), and SQLAlchemy writes ``updated_at =
    now()`` into every ORM update (``onupdate``), so one clock, the
    database's, sets both. ``now()`` is the transaction start time, so rows
    written in one transaction share a timestamp. Bulk or raw SQL updates
    don't change ``updated_at``, because there is no database trigger.

    ``eager_defaults`` adds ``RETURNING`` to inserts and updates, so the new
    values are available right away without an extra query, even after the
    session is closed. A model that defines its own ``__mapper_args__``
    replaces this one and must include ``"eager_defaults": True`` itself.

    Attributes:
        created_at: When the row was inserted, in UTC.
        updated_at: When the row was last changed through the ORM, in UTC.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        sort_order=10,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        sort_order=10,
    )

    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}
