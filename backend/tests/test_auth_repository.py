from datetime import UTC
from datetime import datetime
from datetime import timedelta

from factories import make_refresh_token
from factories import make_user
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth import repository
from app.modules.auth.models import RefreshToken


def test_an_added_refresh_token_is_saved_on_flush(db_session: Session) -> None:
    """A token passed to ``add`` is inserted when the session flushes.

    A query by its hash returns the very same object, so the row in the
    table is this token and not merely some match. ``add`` itself doesn't
    flush or commit; the test flushes, as the service will.
    """
    user = make_user()
    db_session.add(user)
    db_session.flush()

    token = make_refresh_token(user.id)
    repository.add(db_session, token)
    db_session.flush()

    result = db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token.token_hash)
    )

    assert result is token


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

    found_token = repository.get_by_hash(db_session, target_token.token_hash)

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

    found_token = repository.get_by_hash(
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

    found_token = repository.get_by_hash(db_session, revoked_token.token_hash)

    assert found_token is not None
    assert found_token.id == revoked_token.id
    assert found_token.revoked_at == now


def test_revoke_all_revokes_every_active_token_of_the_user(db_session: Session) -> None:
    """Every unrevoked token of the user is revoked with exactly the given time.

    The tokens are read back with a new query, because the UPDATE changes
    the database directly. Comparing with the exact time shows the
    repository records the service's time rather than its own clock.
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

    repository.revoke_all_for_user(db_session, user.id, revoked_at=now)

    user_tokens = (
        db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
        .scalars()
        .all()
    )

    assert len(user_tokens) == 2
    for token in user_tokens:
        assert token.revoked_at == now


def test_revoke_all_leaves_other_users_tokens_alone(db_session: Session) -> None:
    """Revoking one user's tokens leaves another user's token unrevoked.

    A missing user filter would end every session in the hospital at
    once, so this checks the bystander's token directly after the update.
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

    repository.revoke_all_for_user(db_session, revoked_user.id, now)

    untouched_token = db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == other_user.id)
    ).scalar_one()

    assert untouched_token.revoked_at is None


def test_revoke_all_keeps_the_time_of_already_revoked_tokens(db_session: Session) -> None:
    """A token revoked earlier keeps its original revocation time.

    The token is saved already revoked, then revoked again five days
    later. Its time must not move, so the history of when each token was
    rotated or revoked survives a later mass revocation.
    """
    now = datetime.now(UTC)
    later = now + timedelta(days=5)
    user = make_user()

    db_session.add(user)
    db_session.flush()

    db_session.add(make_refresh_token(user.id, revoked_at=now))
    db_session.flush()

    repository.revoke_all_for_user(db_session, user.id, revoked_at=later)

    kept_token = db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    ).scalar_one()

    assert kept_token.revoked_at == now
