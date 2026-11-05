import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from collections.abc import Iterator
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest
from factories import make_refresh_token
from factories import make_user
from sqlalchemy import Engine
from sqlalchemy import create_engine
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import make_url
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.errors import BadRequestError
from app.core.security import generate_refresh_token
from app.core.security import hash_password
from app.core.security import hash_refresh_token
from app.core.security import verify_password
from app.modules.auth import repository
from app.modules.auth import service
from app.modules.auth.models import RefreshToken
from app.modules.auth.schemas import PasswordChange
from app.modules.auth.service import IssuedTokens
from app.modules.users.models import User

PASSWORD = "Correct-Password-1"
NEW_PASSWORD = "New-Password-123"
WRONG_PASSWORD = "Wrong-Password-1"
INVALID_TOKEN = "Invalid or expired token."

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


def _run_migrations(database_url: str) -> None:
    """Bring a database's schema up to date with ``alembic upgrade head``.

    It runs in a subprocess, as the ``apply_migrations`` fixture runs it for
    the test database, because ``migrations/env.py`` reads ``DATABASE_URL``,
    and an in-process call would migrate the development database instead.

    Args:
        database_url: SQLAlchemy URL of the database to migrate.

    Raises:
        Failed: pytest's failure, with Alembic's error output, if the
            migration fails.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env=os.environ | {"DATABASE_URL": database_url},
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"Alembic migration failed:\n{result.stderr}", pytrace=False)


@pytest.fixture(scope="module")
def race_engine() -> Iterator[Engine]:
    """Create a database for these tests alone, migrate it, and drop it afterwards.

    These tests commit real rows, which every connection to their database
    can see. In the shared test database, another test run going at the
    same moment would see them too, and its tests that count every row of
    a table would fail. A database of their own, named after this process,
    keeps the runs apart: no other run sees these rows, and only this
    module's requests ever wait for a lock in it. It is created next to the
    test database, through the server's ``postgres`` database, migrated as
    the test database is, and dropped at the end with ``FORCE``, which
    closes any connection still open to it, even when the migration fails.

    Yields:
        An engine connected to the new database.
    """
    test_database_url = get_settings().test_database_url

    if test_database_url is None:
        pytest.fail("TEST_DATABASE_URL is not set", pytrace=False)

    test_url = make_url(test_database_url)
    race_url = test_url.set(database=f"{test_url.database}_race_{os.getpid()}")
    server = create_engine(test_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    database_name = server.dialect.identifier_preparer.quote(str(race_url.database))

    with server.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)"))
        connection.execute(text(f"CREATE DATABASE {database_name}"))

    engine = create_engine(
        race_url,
        connect_args={"options": "-c timezone=utc", "connect_timeout": 5},
    )

    try:
        _run_migrations(race_url.render_as_string(hide_password=False))
        yield engine
    finally:
        engine.dispose()

        with server.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {database_name} WITH (FORCE)"))

        server.dispose()


@pytest.fixture
def session_factory(race_engine: Engine) -> sessionmaker[Session]:
    """Make sessions that commit for real, each on its own connection.

    A row lock only matters between two transactions, so these tests can't
    use ``db_session``, whose one transaction every query shares and which
    is rolled back at the end. Each request opens its own session from this
    factory, as the application opens one per request, and commits for
    real; ``committed_user`` deletes what a test leaves behind.
    ``expire_on_commit=False`` matches the application's sessions.

    Args:
        race_engine: Engine for the database these tests have to themselves.

    Returns:
        A factory whose sessions run on that database.
    """
    return sessionmaker(bind=race_engine, expire_on_commit=False)


@pytest.fixture
def committed_user(session_factory: sessionmaker[Session]) -> Iterator[User]:
    """Commit a user every connection can see, then delete it and its tokens.

    The user's password is ``PASSWORD``. Deleting the user deletes its
    refresh tokens through ``ON DELETE CASCADE``, so the next test starts
    from an empty database. ``lock_timeout`` makes the cleanup fail after a
    few seconds, rather than hang, if a thread that never finished still
    holds a lock.

    Args:
        session_factory: Makes the sessions that commit and clean up.

    Yields:
        The committed user, detached, with its attributes loaded.
    """
    with session_factory() as session:
        user = make_user(email="concurrency@example.com", password_hash=hash_password(PASSWORD))
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


def _change_password_in_new_session(
    session_factory: sessionmaker[Session],
    user: User,
) -> IssuedTokens:
    """Change a user's password in a session of its own, as one request would.

    The user is loaded in the request's session first, as the
    authentication dependency loads the signed-in user, and the password
    goes from ``PASSWORD`` to ``NEW_PASSWORD``.

    Args:
        session_factory: Makes the request's session.
        user: The user whose password changes.

    Returns:
        The tokens of the new session the change starts.
    """
    with session_factory() as session:
        signed_in_user = session.get(User, user.id)
        assert signed_in_user is not None
        data = PasswordChange(current_password=PASSWORD, new_password=NEW_PASSWORD)

        return service.change_password(session, signed_in_user, data)


def _sign_in_in_new_session(session_factory: sessionmaker[Session], password: str) -> IssuedTokens:
    """Sign in as the committed user in a session of its own, as one request would.

    Args:
        session_factory: Makes the request's session.
        password: The password to sign in with.

    Returns:
        The tokens of the session the sign-in starts.
    """
    with session_factory() as session:
        return service.login(session, "concurrency@example.com", password)


def _deactivate_user_in_new_session(session_factory: sessionmaker[Session], user: User) -> None:
    """Deactivate a user in a session of its own, as staff administration will.

    Args:
        session_factory: Makes the request's session.
        user: The user to deactivate.
    """
    with session_factory() as session:
        session.execute(update(User).where(User.id == user.id).values(is_active=False))
        session.commit()


def _delete_user_in_new_session(
    session_factory: sessionmaker[Session],
    user: User,
    pause: _Pause | None = None,
) -> None:
    """Delete a user in a session of its own, optionally stopping before the commit.

    The ``DELETE`` locks the user's row, and ``ON DELETE CASCADE`` removes
    the user's refresh tokens in the same statement, so a request held at
    ``pause`` holds that lock with both deletions not yet committed.

    Args:
        session_factory: Makes the request's session.
        user: The user to delete.
        pause: Where the request stops, between the ``DELETE`` and the
            commit, or None to commit straight away.
    """
    with session_factory() as session:
        session.execute(delete(User).where(User.id == user.id))

        if pause is not None:
            pause.wait_here()

        session.commit()


def _token_id(session_factory: sessionmaker[Session], raw_token: str) -> uuid.UUID:
    """Return the primary key of the refresh token a raw value belongs to.

    Args:
        session_factory: Makes the session that reads the row.
        raw_token: The raw refresh token.

    Returns:
        The token row's ``id``.
    """
    statement = select(RefreshToken.id).where(
        RefreshToken.token_hash == hash_refresh_token(raw_token)
    )

    with session_factory() as session:
        return session.execute(statement).scalar_one()


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


def _pause_after_the_replacement_lookup(monkeypatch: pytest.MonkeyPatch) -> _Pause:
    """Make the held request stop just after a sign-out has found and locked a replacement.

    The service looks tokens up through the repository module, so replacing
    the function there reaches its calls. The held sign-out stops with the
    rotated token and its replacement both locked, and nothing written yet.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The pause the held request will stop at.
    """
    pause = _Pause()
    real_lookup = repository.get_refresh_token_by_id_for_update

    def lookup_then_pause(session: Session, token_id: uuid.UUID) -> RefreshToken | None:
        """Look the token up as usual, then stop the held request."""
        token = real_lookup(session, token_id)
        pause.wait_here()
        return token

    monkeypatch.setattr(repository, "get_refresh_token_by_id_for_update", lookup_then_pause)
    return pause


def _pause_after_the_password_check(monkeypatch: pytest.MonkeyPatch) -> _Pause:
    """Make the held request stop just after a sign-in has checked its password.

    The auth service imported ``verify_login_password`` by name, so the
    replacement goes into its namespace. The held request stops with the
    check's result in hand and nothing written yet.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The pause the held request will stop at.
    """
    pause = _Pause()
    real_check = service.verify_login_password

    def check_then_pause(password: str, password_hash: str | None) -> bool:
        """Check the password as usual, then stop the held request."""
        is_correct = real_check(password, password_hash)
        pause.wait_here()
        return is_correct

    monkeypatch.setattr(service, "verify_login_password", check_then_pause)
    return pause


def _wait_until_a_request_waits_for_a_lock(engine: Engine) -> None:
    """Return once a statement in the race database is waiting for a lock.

    PostgreSQL lists every session in ``pg_stat_activity``, and a statement
    blocked by another transaction's lock shows ``wait_event_type = 'Lock'``.
    Only the running test's requests use that database, and the held one is
    paused in Python, not in the database, so a waiting statement is the
    competing request's. A sleep would only guess: on a slow run the held
    request could be released before the competing one reached the lock,
    and the test would no longer race them. The polls run in autocommit
    mode, each in a transaction of its own.

    Args:
        engine: Engine for the race database.

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
        engine: Engine for the race database, for the lock check.
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
    race_engine: Engine,
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
        race_engine,
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
    race_engine: Engine,
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
        race_engine,
        pause,
        held=lambda: _sign_out_in_new_session(session_factory, committed_user, raw_token),
        competing=lambda: _refresh_in_new_session(session_factory, raw_token),
    )

    assert held_future.result() is None

    with pytest.raises(AuthenticationError):
        competing_future.result()

    assert _count_tokens(session_factory, committed_user, is_usable=False) == 1
    assert _count_tokens(session_factory, committed_user, is_usable=True) == 0


def test_a_sign_out_that_waits_for_a_refresh_of_its_token_ends_the_new_session_too(
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A sign-out that meets a refresh of the same cookie also ends the token that refresh issues.

    The refresh is held after its checks, with the token locked, so the
    sign-out of the same token has to wait. Released, the refresh rotates
    the token and returns a replacement, which the browser may store after
    the sign-out has deleted the cookie. The sign-out must then revoke the
    replacement, so no token of that session works afterwards. Before the
    fix the sign-out found the token rotated and changed nothing, and the
    replacement kept the session alive.
    """
    raw_token = _commit_refresh_token(session_factory, committed_user)
    pause = _pause_before_issuing_tokens(monkeypatch)

    held_future, competing_future = _race(
        race_engine,
        pause,
        held=lambda: _refresh_in_new_session(session_factory, raw_token),
        competing=lambda: _sign_out_in_new_session(session_factory, committed_user, raw_token),
    )

    refreshed_tokens = held_future.result()

    assert isinstance(refreshed_tokens, IssuedTokens)
    assert competing_future.result() is None
    assert _count_tokens(session_factory, committed_user, is_usable=True) == 0

    with pytest.raises(AuthenticationError):
        _refresh_in_new_session(session_factory, refreshed_tokens.refresh_token)


def test_a_refresh_of_the_replacement_waits_for_the_sign_out_revoking_it(
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A refresh of the replacement waits for the sign-out that is revoking it, then is refused.

    The cookie's token was already rotated, and the sign-out is held right
    after it has locked the replacement. A refresh of that replacement, as
    the browser that received it would send, has to wait for the lock, and
    once the sign-out commits it finds the replacement revoked and is
    refused. Without the lock the refresh would rotate the replacement
    while the sign-out was deciding, and its new token would outlive the
    sign-out.
    """
    raw_replacement = _commit_refresh_token(session_factory, committed_user)
    raw_rotated_token = _commit_refresh_token(
        session_factory,
        committed_user,
        revoked_at=datetime.now(UTC),
        replaced_by_id=_token_id(session_factory, raw_replacement),
    )
    pause = _pause_after_the_replacement_lookup(monkeypatch)

    held_future, competing_future = _race(
        race_engine,
        pause,
        held=lambda: _sign_out_in_new_session(session_factory, committed_user, raw_rotated_token),
        competing=lambda: _refresh_in_new_session(session_factory, raw_replacement),
    )

    assert held_future.result() is None

    with pytest.raises(AuthenticationError):
        competing_future.result()

    assert _count_tokens(session_factory, committed_user, is_usable=True) == 0


# Where the held refresh in the next two tests stops: after all its checks,
# or right after it has locked the token. A refresh that locked the token
# before the user would hold only the token at the second point, and it and
# the competing request would then wait for each other until PostgreSQL
# aborted one, so the second point is what pins the order of the two locks.
HELD_REFRESH_PAUSES = [
    pytest.param(_pause_before_issuing_tokens, id="held-before-issuing-tokens"),
    pytest.param(_pause_after_the_token_lookup, id="held-after-locking-the-token"),
]


@pytest.mark.parametrize("pause_held_refresh", HELD_REFRESH_PAUSES)
def test_the_reuse_alarm_revokes_the_token_of_a_refresh_still_in_flight(
    pause_held_refresh: Callable[[pytest.MonkeyPatch], _Pause],
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """The reuse alarm also ends a session that a refresh is issuing at that moment.

    A thief refreshes with the replacement of a stolen token, and that
    refresh is held with its locks taken. The real user then presents the
    stolen token, which was already rotated, so the alarm goes off. The
    alarm has to wait for the held refresh, then revoke the token that
    refresh issued along with the rest, so the thief's new session ends
    with the others. Before the fix the alarm's revocation saw only the
    tokens committed when it started, and the thief kept a session that
    went on refreshing.
    """
    thief_raw_token = _commit_refresh_token(session_factory, committed_user)
    stolen_raw_token = _commit_refresh_token(
        session_factory,
        committed_user,
        revoked_at=datetime.now(UTC),
        replaced_by_id=_token_id(session_factory, thief_raw_token),
    )
    pause = pause_held_refresh(monkeypatch)

    held_future, competing_future = _race(
        race_engine,
        pause,
        held=lambda: _refresh_in_new_session(session_factory, thief_raw_token),
        competing=lambda: _refresh_in_new_session(session_factory, stolen_raw_token),
    )

    thief_tokens = held_future.result()

    assert isinstance(thief_tokens, IssuedTokens)

    with pytest.raises(AuthenticationError):
        competing_future.result()

    assert _count_tokens(session_factory, committed_user, is_usable=True) == 0

    with pytest.raises(AuthenticationError):
        _refresh_in_new_session(session_factory, thief_tokens.refresh_token)


@pytest.mark.parametrize("pause_held_refresh", HELD_REFRESH_PAUSES)
def test_a_password_change_revokes_the_token_of_a_refresh_still_in_flight(
    pause_held_refresh: Callable[[pytest.MonkeyPatch], _Pause],
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A password change also ends a session another device is refreshing at that moment.

    The other device's refresh is held with its locks taken, and the user
    changes the password on this device. The change has to wait for the
    held refresh, then revoke the token that refresh issued along with the
    rest, while this device keeps the new session the change started.
    Before the fix the change's revocation saw only the tokens committed
    when it started, and the other device stayed signed in after the
    password change.
    """
    other_device_raw_token = _commit_refresh_token(session_factory, committed_user)
    pause = pause_held_refresh(monkeypatch)

    held_future, competing_future = _race(
        race_engine,
        pause,
        held=lambda: _refresh_in_new_session(session_factory, other_device_raw_token),
        competing=lambda: _change_password_in_new_session(session_factory, committed_user),
    )

    other_device_tokens = held_future.result()
    this_device_tokens = competing_future.result()

    assert isinstance(other_device_tokens, IssuedTokens)
    assert isinstance(this_device_tokens, IssuedTokens)

    with pytest.raises(AuthenticationError):
        _refresh_in_new_session(session_factory, other_device_tokens.refresh_token)

    assert isinstance(
        _refresh_in_new_session(session_factory, this_device_tokens.refresh_token),
        IssuedTokens,
    )


def test_a_password_change_is_checked_against_a_change_committed_after_loading(
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A password change is checked against the stored hash as it is now.

    This request loads the user first, as its authentication does. Another
    device then changes the password from ``PASSWORD`` and commits before
    this request continues with the same old password. It must be refused,
    because the stored password is no longer the one it gives. Checked
    against the copy it loaded at the start, it would succeed and silently
    overwrite the other device's change.
    """
    with session_factory() as session:
        signed_in_user = session.get(User, committed_user.id)
        assert signed_in_user is not None

        _change_password_in_new_session(session_factory, committed_user)

        data = PasswordChange(current_password=PASSWORD, new_password="Third-Password-1")

        with pytest.raises(BadRequestError):
            service.change_password(session, signed_in_user, data)

    with session_factory() as session:
        stored_user = session.get(User, committed_user.id)

    assert stored_user is not None
    assert verify_password(NEW_PASSWORD, stored_user.password_hash)


def test_a_password_change_is_refused_when_the_account_is_deactivated_after_loading(
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A password change saves nothing if its account is deactivated after loading.

    This request loads the user first, as its authentication does, and the
    account is then deactivated on another connection. The change reads
    the account again under its lock, so it must refuse with the usual
    token error, as the request's authentication would refuse it now, keep
    the old password, and issue no session. Before the fix it went on with
    the account it had loaded, so the inactive account got a new password
    and a refresh token.
    """
    with session_factory() as session:
        signed_in_user = session.get(User, committed_user.id)
        assert signed_in_user is not None

        _deactivate_user_in_new_session(session_factory, committed_user)

        data = PasswordChange(current_password=PASSWORD, new_password=NEW_PASSWORD)

        with pytest.raises(AuthenticationError) as exc_info:
            service.change_password(session, signed_in_user, data)

    with session_factory() as session:
        stored_user = session.get(User, committed_user.id)

    assert exc_info.value.message == INVALID_TOKEN
    assert stored_user is not None
    assert verify_password(PASSWORD, stored_user.password_hash)
    assert _count_tokens(session_factory, committed_user, is_usable=False) == 0


def test_a_password_change_is_refused_when_the_account_is_deleted_after_loading(
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A password change gets the usual refusal, not a 500, if its account is deleted after loading.

    The app never deletes users, but a development database can be reset
    while a browser still holds a token. The change finds no account under
    its lock, so it must raise the usual token error. Before the fix it
    changed the copy it had loaded, and flushing an ``UPDATE`` that matched
    no row raised SQLAlchemy's ``StaleDataError``, which the API answers
    with a 500.
    """
    with session_factory() as session:
        signed_in_user = session.get(User, committed_user.id)
        assert signed_in_user is not None

        _delete_user_in_new_session(session_factory, committed_user)

        data = PasswordChange(current_password=PASSWORD, new_password=NEW_PASSWORD)

        with pytest.raises(AuthenticationError) as exc_info:
            service.change_password(session, signed_in_user, data)

    assert exc_info.value.message == INVALID_TOKEN


def test_a_refresh_whose_user_is_deleted_while_it_waits_is_refused(
    race_engine: Engine,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A refresh gets the usual refusal when its user is deleted while it waits.

    The app never deletes users, but tests do. The deletion is held after
    its ``DELETE``, with the user's row locked. The refresh still finds the
    token's user, because the deletion isn't committed, and then has to
    wait for that lock. Once the deletion commits, the refresh finds
    neither the user nor the token, which the cascade removed, and must
    raise the usual error rather than fail on the missing token.
    """
    raw_token = _commit_refresh_token(session_factory, committed_user)
    pause = _Pause()

    held_future, competing_future = _race(
        race_engine,
        pause,
        held=lambda: _delete_user_in_new_session(session_factory, committed_user, pause),
        competing=lambda: _refresh_in_new_session(session_factory, raw_token),
    )

    assert held_future.result() is None

    with pytest.raises(AuthenticationError):
        competing_future.result()


# What can happen to an account while a sign-in checks its password. Each
# runs in a session of its own and commits before the sign-in continues.
ACCOUNT_CHANGES_DURING_SIGN_IN = [
    pytest.param(_change_password_in_new_session, id="password-changed"),
    pytest.param(_deactivate_user_in_new_session, id="deactivated"),
    pytest.param(_delete_user_in_new_session, id="deleted"),
]


@pytest.mark.parametrize("change_account", ACCOUNT_CHANGES_DURING_SIGN_IN)
def test_a_sign_in_is_refused_when_the_account_changes_during_its_password_check(
    change_account: Callable[[sessionmaker[Session], User], object],
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A sign-in whose account changes while it checks the password starts no session.

    The sign-in is held right after its check passed, against the account
    as it read it, and the account then changes and commits: its password
    is changed, it is deactivated, or it is deleted. Released, the sign-in
    must be refused with the usual error. Before the fix it went on with
    what it had read, so a sign-in with the old password kept a session
    that the password change should have ended.
    """
    pause = _pause_after_the_password_check(monkeypatch)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=HELD) as pool:
        sign_in = pool.submit(_sign_in_in_new_session, session_factory, PASSWORD)

        try:
            assert pause.reached.wait(TIMEOUT_SECONDS), "the sign-in never reached its pause"
            change_account(session_factory, committed_user)
        finally:
            pause.released.set()

    with pytest.raises(AuthenticationError):
        sign_in.result()


def test_a_password_change_revokes_the_session_of_a_sign_in_still_in_flight(
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """A password change also ends a session that a sign-in is starting at that moment.

    The sign-in is held after its checks, with the account locked, and the
    user changes the password on another device. The change has to wait
    for the held sign-in, then revoke the session it started along with
    the rest, while the changing device keeps its own new session. Before
    the fix the sign-in held no lock, the change didn't wait, and the
    sign-in's session outlived it.
    """
    pause = _pause_before_issuing_tokens(monkeypatch)

    held_future, competing_future = _race(
        race_engine,
        pause,
        held=lambda: _sign_in_in_new_session(session_factory, PASSWORD),
        competing=lambda: _change_password_in_new_session(session_factory, committed_user),
    )

    sign_in_tokens = held_future.result()
    this_device_tokens = competing_future.result()

    assert isinstance(sign_in_tokens, IssuedTokens)
    assert isinstance(this_device_tokens, IssuedTokens)

    with pytest.raises(AuthenticationError):
        _refresh_in_new_session(session_factory, sign_in_tokens.refresh_token)

    assert isinstance(
        _refresh_in_new_session(session_factory, this_device_tokens.refresh_token),
        IssuedTokens,
    )


def test_a_failed_sign_in_checks_the_password_without_locking_the_account(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    committed_user: User,
) -> None:
    """Two failed sign-ins of one account never wait for each other.

    A sign-in with a wrong password is held right after its check. A second
    wrong-password sign-in for the same account must be refused at once,
    without waiting for a lock: ``lock_timeout`` turns any wait into an
    error. If sign-in locked the account before the check, the second
    attempt would wait for the first, while attempts on an unknown email
    never wait, and that difference in time would tell an attacker which
    accounts exist. Sign-in therefore locks only after a password passes.
    """
    pause = _pause_after_the_password_check(monkeypatch)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=HELD) as pool:
        first_sign_in = pool.submit(_sign_in_in_new_session, session_factory, WRONG_PASSWORD)

        try:
            assert pause.reached.wait(TIMEOUT_SECONDS), "the sign-in never reached its pause"

            with session_factory() as session:
                session.execute(text("SET LOCAL lock_timeout = '1s'"))

                with pytest.raises(AuthenticationError):
                    service.login(session, committed_user.email, WRONG_PASSWORD)
        finally:
            pause.released.set()

    with pytest.raises(AuthenticationError):
        first_sign_in.result()
