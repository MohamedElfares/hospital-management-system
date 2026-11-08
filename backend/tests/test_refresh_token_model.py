import secrets
import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import psycopg
import pytest
from factories import make_refresh_token
from factories import make_user
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.auth.models import RefreshToken
from app.modules.users.models import User


@pytest.fixture
def user(db_session: Session) -> User:
    """Save a user that the tokens in a test can belong to.

    Every refresh token needs an existing user because of the foreign key.
    The user is flushed, so its ID exists, but not committed: the test's
    rollback removes it like everything else.

    Args:
        db_session: The test's session.

    Returns:
        The saved user.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()

    return user


def _count_tokens(db_session: Session, user_id: uuid.UUID) -> int:
    """Count a user's refresh tokens by asking the database.

    The tests that delete rows use this instead of the token objects they
    hold: PostgreSQL deletes rows through ON DELETE rules without telling
    the session, so the objects in memory still look present. A query
    always reads the table as it is.

    Args:
        db_session: The test's session.
        user_id: The user whose tokens to count.

    Returns:
        How many refresh token rows reference ``user_id``.
    """
    return db_session.execute(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user_id)
    ).scalar_one()


def test_a_new_refresh_token_is_unrevoked_and_unreplaced(user: User, db_session: Session) -> None:
    """A token saved with only the required fields is usable and unlinked.

    It belongs to the given user, has not been revoked or replaced, and has
    a creation time from the database. The row is read back with
    ``refresh``, so the test checks what PostgreSQL stored, not what Python
    happened to leave unset.
    """
    token = make_refresh_token(user.id)
    db_session.add(token)
    db_session.flush()
    db_session.refresh(token)

    assert token.user_id == user.id
    assert token.revoked_at is None
    assert token.replaced_by_id is None
    assert token.created_at is not None


def test_the_expiry_reads_back_timezone_aware(user: User, db_session: Session) -> None:
    """The expiry survives a round trip unchanged and with a time zone.

    The value read back equals the one written, to the microsecond, and is
    timezone-aware. A plain ``TIMESTAMP`` column would return a naive
    datetime and fail both checks, so this proves the column is
    ``TIMESTAMPTZ``.
    """
    expires_at = datetime.now(UTC) + timedelta(days=7)
    token = make_refresh_token(user.id, expires_at=expires_at)
    db_session.add(token)
    db_session.flush()
    db_session.refresh(token)

    assert token.expires_at == expires_at
    assert token.expires_at.tzinfo is not None


def test_two_refresh_tokens_cannot_share_a_hash(user: User, db_session: Session) -> None:
    """A second token with the same hash is rejected by ``uq_refresh_tokens_token_hash``.

    The hash is set explicitly on both tokens, because the factory gives
    every token a different random one. Uniqueness lets each refresh find
    exactly one row by its hash.
    """
    token_hash = secrets.token_hex(32)
    first_token = make_refresh_token(user.id, token_hash=token_hash)
    second_token = make_refresh_token(user.id, token_hash=token_hash)

    db_session.add(first_token)
    db_session.flush()

    db_session.add(second_token)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    orig = exc_info.value.orig
    assert isinstance(orig, psycopg.errors.UniqueViolation)
    assert orig.diag.constraint_name == "uq_refresh_tokens_token_hash"


def test_a_refresh_token_must_belong_to_an_existing_user(db_session: Session) -> None:
    """A token whose user doesn't exist is rejected by its foreign key.

    The error must come from ``fk_refresh_tokens_user_id_users``, so a
    token can never point at an account that isn't there.
    """
    token = make_refresh_token(uuid.uuid4())
    db_session.add(token)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    orig = exc_info.value.orig
    assert isinstance(orig, psycopg.errors.ForeignKeyViolation)
    assert orig.diag.constraint_name == "fk_refresh_tokens_user_id_users"


@pytest.mark.parametrize("column", ["user_id", "token_hash", "expires_at"])
def test_required_refresh_token_columns_cannot_be_null(
    user: User,
    db_session: Session,
    column: str,
) -> None:
    """Saving a token with a required column set to None is rejected.

    The error must name the same column, so a case can't pass because a
    different column was missing. ``user_id`` goes through the dict too,
    so the factory receives it only once when it is the column under test.
    """
    token = make_refresh_token(**{"user_id": user.id, column: None})
    db_session.add(token)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    orig = exc_info.value.orig
    assert isinstance(orig, psycopg.errors.NotNullViolation)
    assert orig.diag.column_name == column


def test_deleting_a_user_deletes_their_refresh_tokens(user: User, db_session: Session) -> None:
    """Deleting a user makes PostgreSQL delete all of their tokens.

    ``ON DELETE CASCADE`` does the work, not SQLAlchemy: the model has no
    relationship, so the session doesn't know the tokens belong to the
    user. The count is checked before the delete as well, so a query that
    found nothing to begin with can't make the test pass. Two tokens prove
    that every row goes, not just one.
    """
    user_id = user.id
    first_token = make_refresh_token(user.id)
    second_token = make_refresh_token(user.id)

    db_session.add(first_token)
    db_session.add(second_token)
    db_session.flush()

    token_count_before = _count_tokens(db_session, user_id)

    assert token_count_before == 2

    db_session.delete(user)
    db_session.flush()

    remaining = _count_tokens(db_session, user_id)

    assert remaining == 0


def test_deleting_a_replacement_token_clears_the_link_to_it(
    user: User, db_session: Session
) -> None:
    """Deleting a replacement token clears the link to it and keeps the old token.

    The tokens are linked as rotation links them, old to new, and the link
    is checked before the delete, so its absence afterwards can only come
    from ``ON DELETE SET NULL``. The final ``refresh`` also proves the old
    token still exists, because refreshing a deleted row raises an error.
    """
    old_token = make_refresh_token(user.id)
    db_session.add(old_token)
    db_session.flush()

    new_token = make_refresh_token(user.id)
    db_session.add(new_token)
    db_session.flush()

    old_token.replaced_by_id = new_token.id
    db_session.flush()

    db_session.refresh(old_token)
    assert old_token.replaced_by_id == new_token.id

    db_session.delete(new_token)
    db_session.flush()

    db_session.refresh(old_token)

    assert old_token.replaced_by_id is None
