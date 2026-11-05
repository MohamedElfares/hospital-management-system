"""Database queries for refresh tokens.

Every query on the ``refresh_tokens`` table lives here. The service still
changes the rows it has loaded, such as setting ``revoked_at`` when it
rotates a token, and the session writes those changes when it flushes.
Nothing here commits: the auth service owns the transaction, calls these
functions, and commits once per use case, so a sign-in saves its token
and the user's last sign-in time together or not at all. Other modules
must go through the auth service, never through this module.

The lookups return tokens whatever their state, revoked and expired
included: deciding what a revoked token means, such as a sign of theft,
is the service's job, and it can only do that if it sees the token.
"""

# The UUID type of user and token ids; annotates the ids these queries take.
import uuid

# Timestamp type; annotates the revocation time the service passes in.
from datetime import datetime

# Builds the SELECTs that find a token's user, and find and lock a token.
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


def get_refresh_token_user_id_by_hash(session: Session, token_hash: str) -> uuid.UUID | None:
    """Find which user a refresh token belongs to, without locking anything.

    Refresh calls this first, to learn whose row to lock before it locks
    the token itself. A token's user never changes, so the answer can't go
    stale while that lock is awaited. Only the ``user_id`` column is read:
    the token is read again, locked, by ``get_refresh_token_by_hash``.

    Args:
        session: The open database session.
        token_hash: SHA-256 hash of the raw token from the cookie, as
            ``hash_refresh_token`` produces.

    Returns:
        The ID of the token's user, whatever state the token is in, or None
        if no token has this hash.
    """
    statement = select(RefreshToken.user_id).where(RefreshToken.token_hash == token_hash)
    return session.scalar(statement)


def get_refresh_token_by_hash(session: Session, token_hash: str) -> RefreshToken | None:
    """Find the refresh token with a given hash, lock its row, and read it fresh.

    The row is read with ``SELECT ... FOR UPDATE``, so it stays locked until
    the service commits or rolls back. A refresh and a sign-out of the same
    token therefore run one after the other: whichever comes second waits
    here, then reads the row as the first left it, so a refresh never
    rotates a token that a sign-out is revoking, and a sign-out never
    revokes a token while a refresh rotates it. ``populate_existing`` makes
    the result show the row as it is once locked, even when the session
    already holds a copy, which would otherwise come back with the values
    it had before the lock.

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
    statement = (
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.scalar(statement)


def get_refresh_token_by_id_for_update(
    session: Session, token_id: uuid.UUID
) -> RefreshToken | None:
    """Find the refresh token with a given id, lock its row, and read it fresh.

    Sign-out calls this for the token that replaced the one in the cookie,
    when a refresh rotated that one while the sign-out waited for its lock.
    The row is read with ``SELECT ... FOR UPDATE``, as
    ``get_refresh_token_by_hash`` reads the cookie's own token, so a
    refresh of the replacement waits until the sign-out has revoked it,
    then finds it revoked. The lock lasts until the caller's transaction
    ends. ``populate_existing`` makes the result show the row as it is
    once locked, even when the session already holds a copy.

    Revoked and expired tokens are returned too: the caller decides what
    a token's state means. The primary key's index serves the lookup.

    Args:
        session: The open database session. The lock lasts until it
            commits or rolls back.
        token_id: The token's primary key, such as another token's
            ``replaced_by_id``.

    Returns:
        The matching token, in whatever state it is, or None if no token
        has this id.
    """
    return session.get(
        RefreshToken,
        token_id,
        with_for_update=True,
        populate_existing=True,
    )


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

    The caller must already hold the user's row lock, from the users
    service's ``get_user_by_id_for_update``, because the ``UPDATE`` sees
    only the tokens committed when it starts. Every refresh takes that lock
    before it locks a token, and every sign-in before it issues one, so with
    it held no refresh or sign-in of this user is halfway done. One that
    came first has committed, and its new token is revoked here too. One
    that comes later waits: a refresh then finds its own token revoked, and
    a sign-in after a password change finds the password changed. Without
    the lock, a request caught between its checks and its commit would
    issue a token this statement never sees.

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
