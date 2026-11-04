"""Database queries for refresh tokens.

Every query on the ``refresh_tokens`` table lives here. The service still
changes the rows it has loaded, such as setting ``revoked_at`` when it
rotates a token, and the session writes those changes when it flushes.
Nothing here commits: the auth service owns the transaction, calls these
functions, and commits once per use case, so a sign-in saves its token
and the user's last sign-in time together or not at all. Other modules
must go through the auth service, never through this module.

The lookup returns tokens whatever their state, revoked and expired
included: deciding what a revoked token means, such as a sign of theft,
is the service's job, and it can only do that if it sees the token.
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
    """Add a new refresh token to the session, without writing it yet.

    The ``INSERT`` runs at the session's next flush: when the service calls
    ``flush()`` or ``commit()``, or when autoflush runs before the next
    query. That is also where a constraint violation, such as a duplicate
    hash or an unknown user, surfaces.

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
    here, then reads the row as the first left it, already rotated, so the
    service treats it as reuse and ends every session of the user. ADR-0004
    accepts that and asks the web app to send one refresh at a time.
    Without the lock both could see the token as unused and rotate it,
    turning one token into two working sessions with no alarm. Sign-out
    reads through here too, so it waits for a refresh of the same token.

    Revoked and expired tokens are returned too, because the service must
    see a revoked token to detect reuse. The hash is unique, so at most one
    row matches, and the unique constraint's index serves the lookup.

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
    ``UPDATE`` covers any number of tokens, and nothing is committed.
    Tokens that are already revoked keep their original time, so the
    record of when each one was rotated or revoked is never overwritten.
    The service passes the time, so one use case works from one moment:
    after a password change, the revocations and the new session's expiry
    come from the same clock reading.

    The ``UPDATE`` sees the tokens committed when it starts. If a refresh
    of another of the user's tokens holds that row's lock at that moment,
    the statement waits for it, then skips the row, which that refresh has
    just revoked, and misses the token the refresh issued, so that session
    survives.

    The statement runs in the database, and SQLAlchemy then updates only
    the attributes this session has loaded: a token read by a query shows
    the new ``revoked_at``, but one this session created without a
    ``revoked_at`` value still reads None. Callers that read a token
    afterwards should query it again or expire it first.

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
