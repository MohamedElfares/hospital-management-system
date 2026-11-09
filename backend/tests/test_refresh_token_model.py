"""Tests for the refresh_tokens table: a new token's state, its constraints, and its delete rules.

The tests save tokens built by ``make_refresh_token`` into the test
database, whose schema the migrations built, and read back what PostgreSQL
stored, with ``refresh`` or a query, because the session can't see what the
database does on its own. They cover the state a new token starts in, an
expiry that reads back unchanged and timezone-aware, a hash that two tokens
can't share, a user that must exist, the three columns with no default
refusing NULL, and the two ON DELETE rules: deleting a user deletes their
tokens, and deleting a token clears the link that points to it. Each
refusal is checked by the constraint or column it names, so a test can't
pass because some other rule failed. ``TimestampMixin``, which both tables
use, is tested on users in ``tests/test_user_model.py``, and what the auth
repository and service do with these rows in
``tests/test_auth_repository.py`` and ``tests/test_auth_service.py``.
"""

# Random hex values; the hash the duplicate test gives both tokens.
import secrets

# Type of the user ID the count filters on; uuid4() makes an ID no user has.
import uuid

# UTC time zone; the expiry the round-trip test writes is a UTC instant.
from datetime import UTC

# Builds the expiry the round-trip test writes.
from datetime import datetime

# Puts that expiry seven days ahead, the application's default lifetime.
from datetime import timedelta

# PostgreSQL's error classes in the driver; each refusal is checked by its exact class.
import psycopg

# Test framework: the user fixture, raises, and parametrize over the required columns.
import pytest

# Builds a valid unsaved refresh token; each test overrides only the field it is about.
from factories import make_refresh_token

# Builds the valid unsaved user the tokens belong to.
from factories import make_user

# SQL functions; count() for the rows that reference a user.
from sqlalchemy import func

# Builds the count query, which reads the table rather than the session.
from sqlalchemy import select

# What a write the database refuses raises; its orig attribute holds the driver's error.
from sqlalchemy.exc import IntegrityError

# Type of the db_session fixture.
from sqlalchemy.orm import Session

# The model under test; the count query selects from its table.
from app.modules.auth.models import RefreshToken

# Type of the user fixture.
from app.modules.users.models import User


@pytest.fixture
def user(db_session: Session) -> User:
    """Save a user that the tokens in a test can belong to.

    Every refresh token needs an existing user because of the foreign key
    on ``user_id``. Flushing sends the user's ``INSERT`` and gives the user
    its ID, which each token takes; the rollback at the end of the test
    removes the row with everything else the test wrote.

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

    The user deletion test counts with this instead of looking at the
    token objects it holds. PostgreSQL deletes those rows through the
    foreign key's ON DELETE CASCADE without telling the session, so the
    objects stay in it as if nothing had happened: still persistent, their
    values readable, and ``session.get`` hands each one back without a
    query. A query reads the table as it is.

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
    """A token saved with only the required columns starts unrevoked and unreplaced.

    The factory sets only the user, the hash, and the expiry, as the auth
    service does for every token it issues. The token must belong to that
    user, have neither a revocation time, which would make refresh refuse
    it, nor a replacement, and have a creation time from the database.
    The row is read back with ``refresh``, so the values come from the
    stored row: without it, the two columns the test never set would read
    None from the object itself, with no query.
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
    timezone-aware. Refresh compares the expiry with the current UTC time,
    and Python can't order a naive datetime against an aware one, so a
    naive expiry would fail every refresh. A plain ``TIMESTAMP`` column
    would return a naive datetime and fail both checks, since a naive value
    never equals an aware one, so this proves the column is
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

    Refresh and sign-out find a token by the hash of its cookie and take
    the first row that matches, so without the constraint a cookie could
    name either of two tokens. The hash is set explicitly on both tokens,
    because the factory gives every token a different random one.
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

    The user ID is a fresh random UUID, which no saved user has. The error
    must come from ``fk_refresh_tokens_user_id_users``, so a token can
    never point at an account that isn't there.
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

    These are the three columns with no default. SQLAlchemy sends a
    ``None`` in such a column as NULL, which the column's NOT NULL refuses,
    and the error must name the same column, so a case can't pass because
    a different column was missing. The other columns aren't listed: a
    ``None`` ID gets a new UUID, a ``None`` timestamp is left out of the
    ``INSERT`` and takes its server default, and ``revoked_at`` and
    ``replaced_by_id`` allow NULL. ``user_id`` goes into the same dict as
    the column under test, so when it is that column, the later key wins
    and the factory receives it once, as None.
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

    ``ON DELETE CASCADE`` on ``user_id`` does the work, not SQLAlchemy:
    neither model has a relationship, so the session doesn't know the
    tokens belong to the user, and ``_count_tokens`` asks the database. The
    count is checked before the delete as well, so a query that found
    nothing to begin with can't make the test pass, and two tokens show
    that every row goes, not just one. The application deactivates users
    rather than deleting them (plan §7), but tests delete them, and without
    the cascade, deleting a user who holds a token would fail.
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

    The tokens are linked as rotation links them, the old token's
    ``replaced_by_id`` naming the new one, and the link is read back before
    the delete, so its absence afterwards can only come from
    ``ON DELETE SET NULL``; without the rule, the delete itself would fail,
    because the old token still points at the new one. The session keeps
    the old token with its link set, so only the final ``refresh`` sees
    what PostgreSQL changed, and it also proves the old token still exists,
    because refreshing a row that is gone raises ``InvalidRequestError``.
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
