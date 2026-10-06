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
