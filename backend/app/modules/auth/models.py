"""ORM model for refresh tokens, the long-lived half of a sign-in session.

An access token lasts minutes and can't be revoked. A refresh token lasts
days and is valid only while its row here says so, which is what makes
sign-out, deactivation, and theft detection possible. The token itself is
a random value that is never stored: only its SHA-256 hash is, so a leaked
table gives an attacker nothing they can sign in with.
"""

# Python type of the user_id and replaced_by_id attributes.
import uuid

# Python type of the expires_at and revoked_at attributes.
from datetime import datetime

# Column type that maps to TIMESTAMPTZ when timezone=True.
from sqlalchemy import DateTime

# Declares the links to users and to the replacing token, with ON DELETE rules.
from sqlalchemy import ForeignKey

# VARCHAR column type with a maximum length; holds the hex hash.
from sqlalchemy import String

# Annotation that declares a model attribute's Python type and nullability.
from sqlalchemy.orm import Mapped

# Defines a column's database type, constraints, and index.
from sqlalchemy.orm import mapped_column

# Declarative base whose metadata registers the refresh_tokens table.
from app.db.base import Base

# Adds created_at and updated_at set by the database clock.
from app.db.base import TimestampMixin

# Adds the UUID primary key named id.
from app.db.base import UUIDPrimaryKeyMixin


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One refresh token issued to a user, stored as a hash.

    A row is created at sign-in and on every refresh. Refreshing rotates
    the token: the old row is revoked and points to its replacement, and
    a new row is issued. If a revoked token is presented again, it may have
    been stolen, so every token of that user is revoked (plan §8.1).

    A token is usable only while ``revoked_at`` is NULL and ``expires_at``
    is in the future. Revoking keeps the row, so the rotation chain stays
    available for investigation. Nullability comes from each
    ``Mapped`` annotation: ``X`` is NOT NULL and ``X | None`` allows NULL.

    Attributes:
        user_id: The user the token signs in. Deleting the user deletes
            their tokens (ON DELETE CASCADE); in the app users are only
            deactivated, but ``seed-demo --reset`` and tests delete them.
        token_hash: SHA-256 of the token as 64 hex characters. Unique,
            because each refresh finds its row by this value. A fast hash
            is safe here, unlike for passwords, because the token is 256
            random bits and can't be guessed; it also has no salt, so the
            same token always gives the same hash and can be looked up.
        expires_at: When the token stops working, in UTC. Set by the
            service from ``REFRESH_TOKEN_EXPIRE_DAYS``; there is no default
            so a missing value fails instead of picking a lifetime.
        revoked_at: When the token was revoked by rotation, sign-out, or
            reuse detection. None while the token is still usable.
        replaced_by_id: The token issued when this one was rotated. None
            if it was never rotated, so a revoked row with no replacement
            was ended by sign-out or reuse detection. Cleared if the
            replacement row is deleted (ON DELETE SET NULL).
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        index=True,
    )
