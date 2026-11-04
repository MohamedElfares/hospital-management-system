import threading
import time
from collections.abc import Callable
from collections.abc import Iterator
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor

import pytest
from factories import make_refresh_token
from factories import make_user
from sqlalchemy import Engine
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.core.errors import AuthenticationError
from app.core.permissions import Role
from app.core.security import generate_refresh_token
from app.core.security import hash_password
from app.core.security import hash_refresh_token
from app.modules.auth import repository
from app.modules.auth import service
from app.modules.auth.models import RefreshToken
from app.modules.auth.service import IssuedTokens
from app.modules.users.models import User

PASSWORD = "Correct-Password-1"

# The longest any wait in these tests may take. A lock that is missing or
# never released makes a test fail after this long instead of hanging.
TIMEOUT_SECONDS = 10.0

# Thread name prefixes. The pauses stop only the held request's thread.
HELD = "held"
COMPETING = "competing"


class _Pause:
    """A point where the held request stops until the test lets it go on.

    The held request's thread sets ``reached`` when it arrives, still
    holding every lock the request has taken, and waits there. The test
    starts the competing request, waits until a lock blocks it, then sets
    ``released``.

    Attributes:
        reached: Set by the held thread when it arrives at the pause.
        released: Set by the test to let the held thread continue.
    """

    def __init__(self) -> None:
        """Create a pause that no thread has reached yet."""
        self.reached = threading.Event()
        self.released = threading.Event()

    def wait_here(self) -> None:
        """Stop the calling thread if it runs the held request.

        Any other thread returns at once. The held one signals its arrival,
        then blocks until the test releases it.

        Raises:
            TimeoutError: If the test never releases it, so a failing test
                can't leave the thread, and its locks, behind for good.
        """
        if not threading.current_thread().name.startswith(HELD):
            return

        self.reached.set()

        if not self.released.wait(TIMEOUT_SECONDS):
            raise TimeoutError("the test never released the held request")


@pytest.fixture
def session_factory(test_engine: Engine, apply_migrations: None) -> sessionmaker[Session]:
    """Make sessions that commit for real, each on its own connection.

    A row lock only matters between two transactions, so these tests can't
    use ``db_session``, whose one transaction every query shares and which
    is rolled back at the end. Each request opens its own session from this
    factory, as the application opens one per request, and commits for
    real; ``committed_user`` deletes what a test leaves behind.
    ``expire_on_commit=False`` matches the application's sessions.

    Args:
        test_engine: Engine for the test database, shared by the run.
        apply_migrations: Not used directly; naming it makes the schema
            exist first.

    Returns:
        A factory whose sessions run on the test database.
    """
    return sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture
def committed_user(session_factory: sessionmaker[Session]) -> Iterator[User]:
    """Commit a user every connection can see, then delete it and its tokens.

    The user is a Doctor whose password is ``PASSWORD``, not the factory's
    Admin: if the cleanup ever failed, a leftover active Admin would change
    what the ``create-admin`` tests find. Deleting the user deletes its
    refresh tokens through ``ON DELETE CASCADE``. ``lock_timeout`` makes the
    cleanup fail after a few seconds, rather than hang, if a thread that
    never finished still holds a lock.

    Args:
        session_factory: Makes the sessions that commit and clean up.

    Yields:
        The committed user, detached, with its attributes loaded.
    """
    with session_factory() as session:
        user = make_user(
            email="concurrency@example.com",
            password_hash=hash_password(PASSWORD),
            role=Role.DOCTOR,
        )
        session.add(user)
        session.commit()

    yield user

    with session_factory() as session:
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(delete(User).where(User.id == user.id))
        session.commit()


def _commit_refresh_token(
    session_factory: sessionmaker[Session],
    user: User,
    **overrides: object,
) -> str:
    """Commit a refresh token for a user and return its raw value.

    Args:
        session_factory: Makes the session that commits the token.
        user: The user the token belongs to.
        **overrides: Column values that replace the factory's defaults,
            such as ``revoked_at``.

    Returns:
        The raw token, the value a browser would send in its cookie.
    """
    raw_token = generate_refresh_token()

    with session_factory() as session:
        session.add(
            make_refresh_token(user.id, token_hash=hash_refresh_token(raw_token), **overrides)
        )
        session.commit()

    return raw_token


def _count_tokens(session_factory: sessionmaker[Session], user: User, *, is_usable: bool) -> int:
    """Count a user's refresh tokens, all of them or only the unrevoked ones.

    Args:
        session_factory: Makes the session that counts.
        user: The user whose tokens to count.
        is_usable: True to count only tokens that aren't revoked.

    Returns:
        How many of the user's token rows match.
    """
    statement = (
        select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user.id)
    )

    if is_usable:
        statement = statement.where(RefreshToken.revoked_at.is_(None))

    with session_factory() as session:
        return session.execute(statement).scalar_one()


def _refresh_in_new_session(
    session_factory: sessionmaker[Session],
    raw_token: str,
) -> IssuedTokens:
    """Refresh with a token in a session of its own, as one request would.

    Args:
        session_factory: Makes the request's session.
        raw_token: The raw refresh token to present.

    Returns:
        The tokens the refresh issued.
    """
    with session_factory() as session:
        return service.refresh(session, raw_token)


def _sign_out_in_new_session(
    session_factory: sessionmaker[Session],
    user: User,
    raw_token: str,
) -> None:
    """Sign a user out with a token in a session of its own, as one request would.

    Args:
        session_factory: Makes the request's session.
        user: The signed-in user.
        raw_token: The raw refresh token from the cookie.
    """
    with session_factory() as session:
        service.logout(session, user, raw_token)


def _pause_before_issuing_tokens(monkeypatch: pytest.MonkeyPatch) -> _Pause:
    """Make the held request stop just before the auth service issues its tokens.

    The service calls ``generate_refresh_token`` only after every check has
    passed, and after every lock the request takes, so a request stopped
    there holds those locks while the competing request starts.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The pause the held request will stop at.
    """
    pause = _Pause()
    real_generate_refresh_token = service.generate_refresh_token

    def generate_after_pause() -> str:
        """Stop the held request, then create the token as usual."""
        pause.wait_here()
        return real_generate_refresh_token()

    monkeypatch.setattr(service, "generate_refresh_token", generate_after_pause)
    return pause


def _pause_after_the_token_lookup(monkeypatch: pytest.MonkeyPatch) -> _Pause:
    """Make the held request stop just after it has found and locked a refresh token.

    The service looks tokens up through the repository module, so replacing
    the function there reaches its calls. The held request stops with the
    token's row lock taken and nothing written yet.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The pause the held request will stop at.
    """
    pause = _Pause()
    real_lookup = repository.get_refresh_token_by_hash

    def lookup_then_pause(session: Session, token_hash: str) -> RefreshToken | None:
        """Look the token up as usual, then stop the held request."""
        token = real_lookup(session, token_hash)
        pause.wait_here()
        return token

    monkeypatch.setattr(repository, "get_refresh_token_by_hash", lookup_then_pause)
    return pause


def _wait_until_a_request_waits_for_a_lock(engine: Engine) -> None:
    """Return once a statement on the test database is waiting for a lock.

    PostgreSQL lists every session in ``pg_stat_activity``, and a statement
    blocked by another transaction's lock shows ``wait_event_type = 'Lock'``.
    Only this test's requests use the database while it runs, so that is
    the competing request. A sleep would only guess: on a slow run the held
    request could be released before the competing one reached the lock,
    and the test would no longer race them. The polls run in autocommit
    mode, each in a transaction of its own.

    Args:
        engine: Engine for the test database.

    Raises:
        Failed: pytest's failure, if nothing waits within
            ``TIMEOUT_SECONDS``, meaning the lock under test wasn't there.
    """
    query = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
    )
    deadline = time.monotonic() + TIMEOUT_SECONDS

    with engine.connect() as connection:
        connection.execution_options(isolation_level="AUTOCOMMIT")

        while time.monotonic() < deadline:
            if connection.execute(query).scalar_one():
                return

            time.sleep(0.01)

    pytest.fail("the competing request never waited for a lock", pytrace=False)


def _race(
    engine: Engine,
    pause: _Pause,
    held: Callable[[], object],
    competing: Callable[[], object],
) -> tuple[Future[object], Future[object]]:
    """Run two requests so that the competing one meets the held one's locks.

    Each request runs in a thread of its own. The held request starts first
    and stops at ``pause`` with its locks taken. The competing request
    starts next, and the held one is released only once the competing one
    waits for a lock, so every run tests the same interleaving. The held
    request is released in every case, even when a step fails, and leaving
    the executors waits for both threads, so no request keeps a lock past
    the test.

    Args:
        engine: Engine for the test database, for the lock check.
        pause: Where the held request stops.
        held: The request that takes its locks first.
        competing: The request that must wait for them.

    Returns:
        The two requests' futures, held first. ``result()`` returns what a
        request returned, or raises the exception it raised.
    """
    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix=HELD) as held_pool,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix=COMPETING) as competing_pool,
    ):
        held_future = held_pool.submit(held)

        try:
            assert pause.reached.wait(TIMEOUT_SECONDS), "the held request never reached its pause"
            competing_future = competing_pool.submit(competing)
            _wait_until_a_request_waits_for_a_lock(engine)
        finally:
            pause.released.set()

    return held_future, competing_future


def test_a_second_refresh_with_the_same_cookie_waits_and_raises_the_alarm(
    monkeypatch: pytest.MonkeyPatch,
    test_engine: Engine,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """Two refreshes sent together with one cookie never both rotate it.

    The first refresh is held after its checks, with its locks taken. The
    second has to wait for it, then finds the token already rotated and
    raises the reuse alarm, which revokes every token of the user,
    including the one the first refresh just issued. ADR-0004 accepts that
    trade-off, and the web app must send one refresh at a time. Without
    the row lock both would read the token as unused, and one cookie would
    become two working sessions with no alarm.
    """
    raw_token = _commit_refresh_token(session_factory, committed_user)
    pause = _pause_before_issuing_tokens(monkeypatch)

    held_future, competing_future = _race(
        test_engine,
        pause,
        held=lambda: _refresh_in_new_session(session_factory, raw_token),
        competing=lambda: _refresh_in_new_session(session_factory, raw_token),
    )

    assert isinstance(held_future.result(), IssuedTokens)

    with pytest.raises(AuthenticationError):
        competing_future.result()

    assert _count_tokens(session_factory, committed_user, is_usable=True) == 0


def test_a_refresh_waits_for_a_sign_out_of_the_same_token_and_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    test_engine: Engine,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A refresh that meets a sign-out of its token waits, then is refused.

    The sign-out is held after it has found and locked the token, before
    revoking it. The refresh has to wait for that lock; once the sign-out
    commits, the refresh reads the token as revoked, with no replacement,
    and is refused, so a refresh sent at the same moment can't revive the
    session that signed out. Without the lock the refresh would read the
    token as unused and rotate it while the sign-out was still deciding,
    and its new session would outlive the sign-out.
    """
    raw_token = _commit_refresh_token(session_factory, committed_user)
    pause = _pause_after_the_token_lookup(monkeypatch)

    held_future, competing_future = _race(
        test_engine,
        pause,
        held=lambda: _sign_out_in_new_session(session_factory, committed_user, raw_token),
        competing=lambda: _refresh_in_new_session(session_factory, raw_token),
    )

    assert held_future.result() is None

    with pytest.raises(AuthenticationError):
        competing_future.result()

    assert _count_tokens(session_factory, committed_user, is_usable=False) == 1
    assert _count_tokens(session_factory, committed_user, is_usable=True) == 0
