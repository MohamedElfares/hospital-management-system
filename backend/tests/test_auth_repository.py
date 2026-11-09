"""Tests for the auth repository: the queries on the ``refresh_tokens`` table.

The tests call the repository's functions directly with ``db_session``,
the test's own session, and flush what they save, so every query runs
against PostgreSQL inside the test's transaction. ``create_refresh_token``
adds a token that the next flush inserts. The three lookups, the locking
ones by hash and by ID and the unlocked one that returns only a token's
user ID, each answer from the right token rather than from another
user's token saved first, return None for a hash or ID that no token
has, and answer for a revoked or an expired token too, because what a
token's state means is the service's decision: refresh checks reuse
before expiry, so that an old stolen token still raises the alarm. The
two locking lookups also read the row again when the session holds a
copy, so a caller sees the token as the database holds it once locked.
``revoke_all_refresh_tokens_for_user`` revokes every unrevoked token of
one user with the time it is given, leaves other users' tokens alone,
keeps the time of a token revoked earlier, and moves each revoked
token's ``updated_at`` to ``now()``.

The locks can only be seen from a second connection, so
``tests/test_auth_concurrency.py`` tests them, and what the service does
with each token these queries return is tested in
``tests/test_auth_service.py``.
"""

# Random UUIDs; an ID that no saved token has.
import uuid

# UTC time zone; revocation times are timezone-aware UTC, as the service passes them.
from datetime import UTC

# Date and time type; now(UTC) is the revocation time a test records.
from datetime import datetime

# Moves times by days: a second revocation five days later, an expiry a day ago.
from datetime import timedelta

# Builds an unsaved refresh token for a saved user, unrevoked unless a test says otherwise.
from factories import make_refresh_token

# Builds an unsaved User, the owner every token needs.
from factories import make_user

# Builds the queries that read tokens back after a flush or a revocation.
from sqlalchemy import select

# Raw SQL; revokes a token, or backdates its updated_at, past the session and onupdate.
from sqlalchemy import text

# Type of the db_session fixture.
from sqlalchemy.orm import Session

# The auth repository, under test; called as repository.<function>, as the service calls it.
from app.modules.auth import repository

# The refresh_tokens table's ORM model; the read-back queries select it.
from app.modules.auth.models import RefreshToken


def _save_expired_token(db_session: Session) -> RefreshToken:
    """Save a user and a refresh token of theirs that expired a day ago.

    The token is otherwise as the factory builds it, unrevoked and never
    rotated, so the only state a lookup could hold against it is its
    expiry.

    Args:
        db_session: The test's session; the rows are flushed, not committed.

    Returns:
        The saved, expired token.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()

    token = make_refresh_token(user.id, expires_at=datetime.now(UTC) - timedelta(days=1))
    db_session.add(token)
    db_session.flush()

    return token


def test_an_added_refresh_token_is_saved_on_flush(db_session: Session) -> None:
    """A token passed to ``create_refresh_token`` is inserted when the session flushes.

    A query by its hash returns the very same object, so the row in the
    table is this token and not merely some match. ``create_refresh_token``
    only adds the token to the session, so the test flushes, as the auth
    service's next flush or commit does.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()

    token = make_refresh_token(user.id)
    repository.create_refresh_token(db_session, token)
    db_session.flush()

    found_token = db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token.token_hash)
    )

    assert found_token is token


def test_a_token_can_be_found_by_its_hash(db_session: Session) -> None:
    """A hash lookup returns the token with that hash, not the one saved before it.

    The decoy belongs to another user and is saved first, so a lookup that
    ignored the hash and returned the first row would return the decoy.
    """
    decoy_user = make_user(email="other-user@example.com")
    user = make_user()

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()

    decoy_token = make_refresh_token(decoy_user.id)
    target_token = make_refresh_token(user.id)

    db_session.add(decoy_token)
    db_session.add(target_token)
    db_session.flush()

    found_token = repository.get_refresh_token_by_hash_for_update(
        db_session, target_token.token_hash
    )

    assert found_token is not None
    assert found_token.id == target_token.id
    assert found_token.user_id == user.id


def test_an_unknown_hash_finds_no_token(db_session: Session) -> None:
    """A hash that no token has returns None, even with a token in the table."""
    user = make_user()
    db_session.add(user)
    db_session.flush()

    existing_token = make_refresh_token(user.id)
    db_session.add(existing_token)
    db_session.flush()

    found_token = repository.get_refresh_token_by_hash_for_update(
        db_session,
        "unknown",
    )

    assert found_token is None


def test_a_revoked_token_is_still_found_by_its_hash(db_session: Session) -> None:
    """A revoked token is returned by its hash, with its revocation time intact.

    Reuse detection depends on this: the service can only recognise a
    stolen token if the lookup hands back revoked tokens instead of
    treating them as unknown.
    """
    now = datetime.now(UTC)
    user = make_user()
    db_session.add(user)
    db_session.flush()

    revoked_token = make_refresh_token(user.id, revoked_at=now)
    db_session.add(revoked_token)
    db_session.flush()

    found_token = repository.get_refresh_token_by_hash_for_update(
        db_session, revoked_token.token_hash
    )

    assert found_token is not None
    assert found_token.id == revoked_token.id
    assert found_token.revoked_at == now


def test_an_expired_token_is_still_found_by_its_hash(db_session: Session) -> None:
    """The hash lookup returns a token whose expiry has passed.

    Refresh checks reuse before expiry, so a rotated token raises the
    alarm however old it is. A lookup that skipped expired tokens would
    hand refresh nothing to check, and an old stolen token would get a
    quiet 401 instead of the alarm.
    """
    token = _save_expired_token(db_session)

    found_token = repository.get_refresh_token_by_hash_for_update(db_session, token.token_hash)

    assert found_token is token


def test_a_locked_token_lookup_reads_the_row_as_it_is_now(db_session: Session) -> None:
    """The locking lookup replaces a copy of the token the session already holds.

    The copy is read back first, so it holds every column, as a token
    loaded by a query does; a column the session never loaded would be
    filled in fresh anyway and prove nothing. The token is then revoked in
    the database through plain SQL, which leaves that copy unrevoked. The
    lookup must still report it revoked: a lock is only worth taking if
    the row read under it is the one the database holds, or a refresh
    could rotate a token that a sign-out had just revoked.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()

    token = make_refresh_token(user.id)
    db_session.add(token)
    db_session.flush()
    db_session.refresh(token)

    db_session.execute(
        text("UPDATE refresh_tokens SET revoked_at = now() WHERE id = :id"),
        {"id": token.id},
    )

    found_token = repository.get_refresh_token_by_hash_for_update(db_session, token.token_hash)

    assert found_token is token
    assert token.revoked_at is not None


def test_a_token_can_be_found_by_its_id_whatever_its_state(db_session: Session) -> None:
    """An ID lookup returns the token with that ID, even a revoked one.

    The decoy belongs to another user and is saved first, so a lookup that
    returned the wrong row would show it. The target is revoked, because
    sign-out looks a replacement up whatever its state and decides itself
    what that state means.
    """
    revoked_at = datetime.now(UTC)
    decoy_user = make_user(email="other-user@example.com")
    user = make_user()

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()

    decoy_token = make_refresh_token(decoy_user.id)
    target_token = make_refresh_token(user.id, revoked_at=revoked_at)

    db_session.add(decoy_token)
    db_session.add(target_token)
    db_session.flush()

    found_token = repository.get_refresh_token_by_id_for_update(db_session, target_token.id)

    assert found_token is not None
    assert found_token.id == target_token.id
    assert found_token.user_id == user.id
    assert found_token.revoked_at == revoked_at


def test_an_expired_token_is_still_found_by_its_id(db_session: Session) -> None:
    """The ID lookup returns a token whose expiry has passed.

    As with a revoked token, sign-out looks a replacement up whatever its
    state and decides itself what that state means.
    """
    token = _save_expired_token(db_session)

    found_token = repository.get_refresh_token_by_id_for_update(db_session, token.id)

    assert found_token is token


def test_an_unknown_id_finds_no_token(db_session: Session) -> None:
    """An ID that no token has returns None, even with a token in the table."""
    user = make_user()
    db_session.add(user)
    db_session.flush()

    db_session.add(make_refresh_token(user.id))
    db_session.flush()

    assert repository.get_refresh_token_by_id_for_update(db_session, uuid.uuid4()) is None


def test_a_locked_token_lookup_by_id_reads_the_row_as_it_is_now(db_session: Session) -> None:
    """The locking ID lookup replaces a copy of the token the session already holds.

    As in the hash lookup's test, the copy is read back first, so it holds
    every column, and the token is then revoked through plain SQL, which
    leaves that copy unrevoked. The lookup must still report it revoked: a
    lock is only worth taking if the row read under it is the one the
    database holds.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()

    token = make_refresh_token(user.id)
    db_session.add(token)
    db_session.flush()
    db_session.refresh(token)

    db_session.execute(
        text("UPDATE refresh_tokens SET revoked_at = now() WHERE id = :id"),
        {"id": token.id},
    )

    found_token = repository.get_refresh_token_by_id_for_update(db_session, token.id)

    assert found_token is token
    assert token.revoked_at is not None


def test_the_user_of_a_token_is_found_by_its_hash(db_session: Session) -> None:
    """The owner lookup returns the user of the token with that hash, even a revoked one.

    The decoy belongs to another user and is saved first, so a lookup that
    ignored the hash would return the wrong user. The target token is
    revoked, because refresh needs its user to lock even when the token
    turns out to be a stolen copy.
    """
    decoy_user = make_user(email="other-user@example.com")
    user = make_user()

    db_session.add(decoy_user)
    db_session.add(user)
    db_session.flush()

    decoy_token = make_refresh_token(decoy_user.id)
    target_token = make_refresh_token(user.id, revoked_at=datetime.now(UTC))

    db_session.add(decoy_token)
    db_session.add(target_token)
    db_session.flush()

    found_user_id = repository.get_refresh_token_user_id_by_hash(
        db_session, target_token.token_hash
    )

    assert found_user_id == user.id


def test_the_user_of_an_expired_token_is_still_found_by_its_hash(db_session: Session) -> None:
    """The owner lookup returns the user of a token whose expiry has passed.

    Refresh finds the token's user first, to lock the user's row before it
    checks anything, so an owner lookup that skipped expired tokens would
    end refresh before its reuse check, and an old stolen token would raise
    no alarm.
    """
    token = _save_expired_token(db_session)

    found_user_id = repository.get_refresh_token_user_id_by_hash(db_session, token.token_hash)

    assert found_user_id == token.user_id


def test_an_unknown_hash_finds_no_user_id(db_session: Session) -> None:
    """A hash that no token has returns None, even with a token in the table."""
    user = make_user()
    db_session.add(user)
    db_session.flush()

    db_session.add(make_refresh_token(user.id))
    db_session.flush()

    assert repository.get_refresh_token_user_id_by_hash(db_session, "unknown") is None


def test_revoke_all_refresh_tokens_revokes_every_active_token_of_the_user(
    db_session: Session,
) -> None:
    """Every unrevoked token of the user is revoked with exactly the given time.

    The tokens are read back with a query. The session created them
    without a ``revoked_at`` value, so it never loaded one, and the
    ``UPDATE`` leaves such a token as it is: ``first_token.revoked_at``
    would still read None. The query fills the value in from the stored
    row. Comparing with the exact time shows the repository records the
    service's time rather than its own clock.
    """
    now = datetime.now(UTC)
    user = make_user()

    db_session.add(user)
    db_session.flush()

    first_token = make_refresh_token(user.id)
    second_token = make_refresh_token(user.id)

    db_session.add(first_token)
    db_session.add(second_token)
    db_session.flush()

    repository.revoke_all_refresh_tokens_for_user(db_session, user.id, revoked_at=now)

    user_tokens = (
        db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
        .scalars()
        .all()
    )

    assert len(user_tokens) == 2
    for token in user_tokens:
        assert token.revoked_at == now


def test_revoke_all_refresh_tokens_leaves_other_users_tokens_alone(db_session: Session) -> None:
    """Revoking one user's tokens leaves another user's token unrevoked.

    A missing user filter would end every session in the hospital at
    once, so this reads the bystander's stored revocation time after the
    update, which the query fills in as it does in the test above.
    """
    now = datetime.now(UTC)
    revoked_user = make_user()
    other_user = make_user(email="other-user@example.com")

    db_session.add(revoked_user)
    db_session.add(other_user)
    db_session.flush()

    other_token = make_refresh_token(other_user.id)
    revoked_user_token = make_refresh_token(revoked_user.id)

    db_session.add(other_token)
    db_session.add(revoked_user_token)
    db_session.flush()

    repository.revoke_all_refresh_tokens_for_user(db_session, revoked_user.id, now)

    untouched_token = db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == other_user.id)
    ).scalar_one()

    assert untouched_token.revoked_at is None


def test_revoke_all_refresh_tokens_keeps_the_time_of_already_revoked_tokens(
    db_session: Session,
) -> None:
    """A token revoked earlier keeps its original revocation time.

    The token is saved already revoked, then revoked again five days
    later. Its time must not move, so the history of when each token was
    rotated or revoked survives a later mass revocation. The session holds
    only a weak reference to a saved object, and the test never keeps the
    token in a variable, so the token is gone from the session after the
    flush and the query reads the stored time. A token kept in a variable
    would come back as the session holds it, and the test could no longer
    see what the ``UPDATE`` stored.
    """
    now = datetime.now(UTC)
    later = now + timedelta(days=5)
    user = make_user()

    db_session.add(user)
    db_session.flush()

    db_session.add(make_refresh_token(user.id, revoked_at=now))
    db_session.flush()

    repository.revoke_all_refresh_tokens_for_user(db_session, user.id, revoked_at=later)

    kept_token = db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    ).scalar_one()

    assert kept_token.revoked_at == now


def test_revoke_all_refresh_tokens_moves_updated_at_to_now(db_session: Session) -> None:
    """The bulk revocation sets each revoked token's ``updated_at`` to ``now()``.

    ``TimestampMixin``'s ``onupdate`` adds ``updated_at = now()`` to this
    ``UPDATE`` statement too, not only to the updates a flush writes, so
    the column tells when a revoked token last changed. ``now()`` is the
    transaction's start time and stays fixed for the test, so the token is
    first backdated with raw SQL, which skips ``onupdate``, and checked to
    hold the old time, as ``test_an_update_moves_updated_at_to_now`` in
    ``tests/test_user_model.py`` does for an update through the ORM. After
    the revocation, ``updated_at`` must be back at ``created_at``, the
    insert's ``now()``. A mixin that set the column in a mapper event
    instead would pass that test and fail this one, because a mapper event
    runs only when the session flushes an object.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()

    token = make_refresh_token(user.id)
    db_session.add(token)
    db_session.flush()

    backdated = datetime(2000, 1, 1, tzinfo=UTC)
    stored_updated_at = db_session.execute(
        text(
            "UPDATE refresh_tokens SET updated_at = :backdated "
            "WHERE id = :token_id RETURNING updated_at"
        ),
        {"backdated": backdated, "token_id": token.id},
    ).scalar_one()

    assert stored_updated_at == backdated

    repository.revoke_all_refresh_tokens_for_user(db_session, user.id, datetime.now(UTC))
    db_session.refresh(token)

    assert token.updated_at == token.created_at
