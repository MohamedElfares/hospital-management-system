"""Database queries for refresh tokens.

The repository is the only layer that queries the ``refresh_tokens`` table.
It never commits: the auth service owns the transaction, calls these
functions, and commits once per use case, so a sign-in saves its token and
the user's last sign-in time together or not at all. Other modules must go
through the auth service, never through this module.

Lookups return tokens whatever their state, revoked and expired included:
deciding what a revoked token means, such as a sign of theft, is the
service's job, and it can only do that if it sees the token.
"""

# The UUID type of user ids; annotates whose tokens are revoked.
import uuid

# Timestamp type; annotates the revocation time the service passes in.
from datetime import datetime

# Builds the SELECT that finds and locks a token by its hash.
from sqlalchemy import select

# Builds one UPDATE that revokes many tokens at once.
from sqlalchemy import update

# The database session the service passes in.
from sqlalchemy.orm import Session

# The refresh_tokens table's ORM model.
from app.modules.auth.models import RefreshToken


def create_refresh_token(session: Session, token: RefreshToken) -> None:
    """Register a new refresh token with the session.

    Nothing is written yet: the row is inserted when the service flushes or
    commits, which is where constraint violations such as a duplicate hash
    or an unknown user surface.

    Args:
        session: The open database session.
        token: The new, unsaved token. It holds only the hash of the raw
            token, never the raw value.
    """
    session.add(token)


def get_refresh_token_by_hash(session: Session, token_hash: str) -> RefreshToken | None:
    """Find the refresh token with a given hash and lock its row.

    The row is read with ``SELECT ... FOR UPDATE``, so it stays locked until
    the service commits or rolls back. Two refreshes sent at the same moment
    with the same cookie therefore run one after the other: the second waits
    here, then reads the row as the first left it, already revoked. Without
    the lock both could see the token as unused and rotate it, turning one
    token into two valid ones and slipping past reuse detection.

    Revoked and expired tokens are returned too, because the service must
    see a revoked token to detect reuse. The hash is unique, so at most one
    row matches, and its index makes the lookup fast.

    Args:
        session: The open database session. The lock lasts until it
            commits or rolls back.
        token_hash: SHA-256 hash of the raw token from the cookie, as
            ``hash_refresh_token`` produces.

    Returns:
        The matching token, in whatever state it is, or None if no token
        has this hash.
    """
    statement = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    return session.scalar(statement)


def revoke_all_refresh_tokens_for_user(
    session: Session, user_id: uuid.UUID, revoked_at: datetime
) -> None:
    """Revoke every refresh token of one user that isn't revoked yet.

    Used whenever all of a user's sessions must end at once: when a rotated
    token is reused, on password change, and later on deactivation. One
    ``UPDATE`` covers any number of tokens. Tokens that are already revoked
    keep their original time, so the record of when each one was rotated
    or revoked is never overwritten. The service passes the time, so every
    timestamp in one use case is the same. Nothing is committed.

    The statement changes the database directly. Objects this session has
    already loaded may still show old values, so callers that read them
    afterwards should query again or expire them first.

    Args:
        session: The open database session.
        user_id: The user whose sessions end.
        revoked_at: The revocation time to record, timezone-aware UTC.
    """
    statement = (
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )

    session.execute(statement)
