"""Race tests for the auth service: the row locks that keep concurrent requests apart.

A row lock shows only between two transactions, so these tests can't run in
``db_session``, whose one transaction every query shares and which is rolled
back at the end, as the rest of the suite does. Each request runs in a
session of its own, as the application opens one per request, built by the
application's ``SessionLocal`` so it has the same options, and commits for
real, on a database these tests have to themselves: ``race_engine`` creates
it next to the test database, named after this process, migrates it as the
test database is migrated, and drops it when the module ends.
``committed_user`` commits the one account every test uses, whose password
is ``PASSWORD``, and deletes it afterwards, its refresh tokens with it, so no
row of one test reaches the next.

A race runs two requests, each in a thread of its own. The held request goes
first and stops at a pause, which the test puts in its path by replacing a
function the service calls, or, for a deletion, in the helper that runs it.
There it waits, still holding the locks it has taken. The competing request
starts next, and ``_race`` releases the held one only once PostgreSQL shows a
statement waiting for a lock, so every run tests the same interleaving and no
sleep decides it. A request that ends before its turn fails the test at once,
with its own error if it raised one: a competing request that goes through
because the lock under test is missing, or a request with a bug in it, which
then shows as itself rather than as a lock or a pause that never came. The
first test pins that, and the second that each request's session comes from
``SessionLocal``. A few tests run a second request to its end while the
first is held, to show that it never waits, and a few commit a change from
another connection between the moment a request loads the account and the
moment it locks it.

The refresh and sign-out races: two refreshes with one cookie run one after
the other, because the second waits for the user's row lock, and that one
raises the reuse alarm, which also ends the session the first one started. A
sign-out locks tokens but never the user, so a refresh that meets a sign-out
of its token takes the user's lock, waits for the token's, and is refused; a
sign-out that waits for a refresh of its token revokes the replacement that
refresh issues; and a refresh of a replacement waits for the sign-out that is
revoking it, and is refused. The reuse alarm waits for a refresh still in
flight, held after its checks or right after it has locked the token, and
then revokes the token that refresh issued. A refresh whose user is deleted
while it waits for the user's lock is refused with the error every rejected
token gets.

The password change and sign-in races: a password change revokes the token of
a refresh still in flight, held at either of those points, and never waits
for a refresh that has only found its user. It checks the current password
against a change committed after the request loaded the account, and refuses
an account deactivated or deleted after loading with the usual token error. A
sign-in whose account changes during its password check, because the
password was changed or the account deactivated or deleted, is refused; a
password change revokes the session of a sign-in still in flight; and a
failed sign-in checks the password without locking the account, so failed
attempts on one account never wait for each other.

The same use cases without a competing request are tested in
``tests/test_auth_service.py``, the routes in ``tests/test_auth_api.py``, and
the repository's lookups in ``tests/test_auth_repository.py``.
"""

# Process ID, which names the race database, and the environment the Alembic subprocess inherits.
import os

# Runs alembic upgrade head against the race database in a process of its own.
import subprocess

# The running Python, so the Alembic subprocess uses this virtual environment's.
import sys

# Events that hold and release a request, and the thread name that marks the held one.
import threading

# Deadlines for the waits, the short sleep between two polls, and how long a failed race took.
import time

# Type of a token row's primary key, and of the user ID refresh's first lookup returns.
import uuid

# Type of the requests a race runs, of the callables tests take, and of SessionFactory.
from collections.abc import Callable

# Return type of the fixtures that clean up after their yield.
from collections.abc import Iterator

# Type of a running request: what _race returns, and what the waits watch for an early end.
from concurrent.futures import Future

# Runs each request in a named thread of its own, and waits for it before the test ends.
from concurrent.futures import ThreadPoolExecutor

# UTC time zone, for the revocation time of a token a test commits as already rotated.
from datetime import UTC

# The current time: when a test's already rotated token was revoked.
from datetime import datetime

# Binds SessionLocal to the race engine, so each request opens SessionLocal(bind=race_engine).
from functools import partial

# Finds backend/, the directory Alembic runs in.
from pathlib import Path

# Test framework: fixtures, parametrize, raises, fail, and the monkeypatch type.
import pytest

# Builds an unsaved refresh token; _commit_refresh_token gives it a real token's hash.
from factories import make_refresh_token

# Builds the unsaved account committed_user commits.
from factories import make_user

# Type of the race database's engine.
from sqlalchemy import Engine

# Builds the race database's engine, and one for the server's postgres database that creates it.
from sqlalchemy import create_engine

# Deletes the committed user, its tokens going with it: the cleanup, and the tests that delete it.
from sqlalchemy import delete

# SQL count(), for counting a user's tokens.
from sqlalchemy import func

# Parses the test database's URL, so the race database's URL can be built from it.
from sqlalchemy import make_url

# Builds the queries that count a user's tokens and find a token's ID.
from sqlalchemy import select

# Raw SQL: creating and dropping the database, lock_timeout, and the poll of pg_stat_activity.
from sqlalchemy import text

# Deactivates the committed user from another connection.
from sqlalchemy import update

# Type of each request's session.
from sqlalchemy.orm import Session

# Cached settings; the race database is named after TEST_DATABASE_URL's database.
from app.core.config import get_settings

# What a refused sign-in, refresh, or password change raises, which the API answers with 401.
from app.core.errors import AuthenticationError

# What a password change with a stale current password raises, which the API answers with 400.
from app.core.errors import BadRequestError

# Machine-readable error codes; a refresh refused after its user's deletion gets the generic one.
from app.core.errors import ErrorCode

# Makes the raw value of a token a test commits.
from app.core.security import generate_refresh_token

# Hashes PASSWORD with Argon2id for the committed user, so it can sign in.
from app.core.security import hash_password

# Hashes a raw token as the service stores it; commits a token and finds its row.
from app.core.security import hash_refresh_token

# Checks a password against a stored hash; tells which password an account has after a race.
from app.core.security import verify_password

# The application's session factory; each request's session comes from it, with its options.
from app.db.session import SessionLocal

# The auth repository as a module, so the pauses can replace the lookups the service calls.
from app.modules.auth import repository

# The auth service, under test, as a module, so the pauses can replace names it looks up.
from app.modules.auth import service

# The refresh_tokens table's ORM model; the counts and the ID lookup query it.
from app.modules.auth.models import RefreshToken

# Validated password change input, built as the route receives it.
from app.modules.auth.schemas import PasswordChange

# What sign-in, refresh, and a password change return; a request that succeeded returns one.
from app.modules.auth.service import IssuedTokens

# The users table's ORM model: the committed account, and the deletions and updates of it.
from app.modules.users.models import User

# What session_factory gives the tests: called with no arguments, it opens a
# session on the race database, as SessionLocal() opens one in a request.
SessionFactory = Callable[[], Session]

# The committed user's password, a valid new one that differs from it, and a
# wrong one, for the failed sign-ins.
PASSWORD = "Correct-Password-1"
NEW_PASSWORD = "New-Password-123"
WRONG_PASSWORD = "Wrong-Password-1"

# The message every rejected token gets, written out rather than imported from
# the service, so a changed text fails here.
INVALID_TOKEN = "Invalid or expired token."

# How long a test waits for a request to reach its pause and for a lock wait
# to show, and how long a held request waits for the test to release it. A
# pause or a lock wait that never comes, or a release that never does, fails
# the test after this long instead of hanging it; a request that ends first
# fails it at once.
TIMEOUT_SECONDS = 10.0

# Thread name prefixes; each executor names its thread with one. A pause stops
# only a thread whose name starts with HELD, so the competing request, and the
# test itself, pass straight through the same replaced functions.
HELD = "held"
COMPETING = "competing"


class _Pause:
    """A point where the held request stops until the test lets it go on.

    The held request's thread sets ``reached`` when it arrives, still
    holding every lock the request has taken, and waits there; every other
    thread passes straight through. While it waits, the test runs the
    competing request, through ``_race`` until a lock blocks it, or to its
    end in a test that shows the competing request never waits, and then
    sets ``released``.

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

        A thread runs the held request when its name starts with ``HELD``,
        the prefix the held request's executor gives its thread. Any other
        thread returns at once. The held one signals its arrival, then
        blocks until the test releases it.

        Raises:
            TimeoutError: If the test doesn't release it within
                ``TIMEOUT_SECONDS``, so a failing test can't leave the
                thread, and its locks, behind for good: the request fails,
                and closing its session rolls back and releases its locks.
        """
        if not threading.current_thread().name.startswith(HELD):
            return

        self.reached.set()

        if not self.released.wait(TIMEOUT_SECONDS):
            raise TimeoutError("the test never released the held request")


def _run_migrations(database_url: str) -> None:
    """Bring a database's schema up to date with ``alembic upgrade head``.

    Alembic runs in a subprocess with ``DATABASE_URL`` set to the given
    database, as the ``apply_migrations`` fixture runs it for the test
    database, because ``migrations/env.py`` takes its URL from
    ``get_settings().database_url``. In this process that cached value is
    the development database's, so an in-process call would migrate the
    development database instead.

    Args:
        database_url: SQLAlchemy URL of the database to migrate, with its
            password, since the subprocess connects with it.

    Raises:
        pytest.fail.Exception: If the migration fails, with Alembic's error
            output in the message.
    """
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env=os.environ | {"DATABASE_URL": database_url},
        check=False,
        capture_output=True,
        text=True,
    )

    if upgrade.returncode != 0:
        pytest.fail(f"Alembic migration failed:\n{upgrade.stderr}", pytrace=False)


@pytest.fixture(scope="module")
def race_engine() -> Iterator[Engine]:
    """Create a database for these tests alone, migrate it, and drop it afterwards.

    These tests commit real rows, which every connection to their database
    can see. In the shared test database, another test run going at the
    same moment would see them too, and its tests that count every row of
    a table would fail. A database of their own, named after this process,
    keeps the runs apart: no other run sees these rows, and only this
    module's requests ever wait for a lock in it.

    It is created next to the test database, through the server's
    ``postgres`` database, so the test database's role must be allowed to
    create databases, as the ``hms`` superuser of the Compose and CI
    containers is; for a role that isn't, every test here errors at setup.
    A database left with the same name by a run that was killed, whose
    process ID this run reuses, is dropped first. The new one is migrated
    as the test database is, and dropped at the end with ``FORCE``, even
    when the migration failed. ``FORCE`` closes every connection still open
    to it, a stuck request's too, while ``engine.dispose()`` closes only
    the connections back in the pool. The engine connects as the test
    engine does: timestamps come back in UTC, and an unreachable server
    fails within seconds.

    Yields:
        An engine connected to the new database.

    Raises:
        pytest.fail.Exception: If ``TEST_DATABASE_URL`` isn't set, or the
            migration fails, with Alembic's error output in the message.
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
def session_factory(race_engine: Engine) -> SessionFactory:
    """Make sessions that commit for real, each on its own connection.

    A row lock only matters between two transactions, so these tests can't
    use ``db_session``, whose one transaction every query shares and which
    is rolled back at the end. Each request opens its own session from this
    factory, as the application opens one per request, and commits for
    real; ``committed_user`` deletes what a test leaves behind.

    The sessions are built by the application's ``SessionLocal``, as
    ``db_session`` is, bound to the race database in place of the engine
    ``SessionLocal`` holds, which stays bound to the development database.
    They therefore have the application's options, ``expire_on_commit=False``
    among them, and an option ``SessionLocal`` gains later reaches them too,
    so the races run in sessions that behave as a request's do.

    Args:
        race_engine: Engine for the database these tests have to themselves.

    Returns:
        A function that opens a new session on that database each time it
        is called.
    """
    return partial(SessionLocal, bind=race_engine)


@pytest.fixture
def committed_user(session_factory: SessionFactory) -> Iterator[User]:
    """Commit a user every connection can see, then delete it and its tokens.

    The user is ``concurrency@example.com``, whose password is
    ``PASSWORD``, the only account any test here commits. Deleting it
    deletes its refresh tokens through ``ON DELETE CASCADE``, so no row of
    one test reaches the next. ``SET LOCAL lock_timeout`` makes the cleanup
    fail after five seconds, rather than hang, if a request that never
    finished still holds a lock on the user's row or on a token's;
    ``LOCAL`` keeps the setting to the cleanup's own transaction.

    Args:
        session_factory: Makes the sessions that commit and clean up.

    Yields:
        The committed user, detached, with the values it was saved with,
        so reading an attribute needs no session.
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
    session_factory: SessionFactory,
    user: User,
    **overrides: object,
) -> str:
    """Commit a refresh token for a user and return its raw value.

    The row stores only the token's hash, as the service stores it, so the
    raw value returned is the token's only copy.

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


def _count_tokens(session_factory: SessionFactory, user: User, *, is_unrevoked_only: bool) -> int:
    """Count a user's refresh tokens, all of them or only the unrevoked ones.

    Args:
        session_factory: Makes the session that counts.
        user: The user whose tokens to count.
        is_unrevoked_only: True to count only tokens that aren't revoked,
            False to count every token, revoked or not.

    Returns:
        How many of the user's token rows match.
    """
    statement = (
        select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user.id)
    )

    if is_unrevoked_only:
        statement = statement.where(RefreshToken.revoked_at.is_(None))

    with session_factory() as session:
        return session.execute(statement).scalar_one()


def _refresh_in_new_session(
    session_factory: SessionFactory,
    raw_token: str,
) -> IssuedTokens:
    """Refresh with a token in a session of its own, as one request would.

    Args:
        session_factory: Makes the request's session.
        raw_token: The raw refresh token to present.

    Returns:
        The tokens the refresh issued.

    Raises:
        AuthenticationError: If refresh refuses the token.
    """
    with session_factory() as session:
        return service.refresh(session, raw_token)


def _sign_out_in_new_session(
    session_factory: SessionFactory,
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
    session_factory: SessionFactory,
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

    Raises:
        AuthenticationError: If the account was deactivated or deleted
            after it was loaded.
        BadRequestError: If ``PASSWORD`` is no longer the stored password.
    """
    with session_factory() as session:
        signed_in_user = session.get(User, user.id)
        assert signed_in_user is not None
        data = PasswordChange(current_password=PASSWORD, new_password=NEW_PASSWORD)

        return service.change_password(session, signed_in_user, data)


def _sign_in_in_new_session(session_factory: SessionFactory, password: str) -> IssuedTokens:
    """Sign in as the committed user in a session of its own, as one request would.

    The email is ``committed_user``'s, typed here as the fixture saves it.

    Args:
        session_factory: Makes the request's session.
        password: The password to sign in with.

    Returns:
        The tokens of the session the sign-in starts.

    Raises:
        AuthenticationError: If the sign-in is refused.
    """
    with session_factory() as session:
        return service.login(session, "concurrency@example.com", password)


def _deactivate_user_in_new_session(session_factory: SessionFactory, user: User) -> None:
    """Deactivate a user in a session of its own, as another request would.

    Only ``is_active`` changes. Deactivation through staff administration
    (ADM-2) will also revoke the user's refresh tokens (plan §8.1); the
    tests that use this need only the flag, which sign-in and a password
    change read again once they hold the account's lock.

    Args:
        session_factory: Makes the request's session.
        user: The user to deactivate.
    """
    with session_factory() as session:
        session.execute(update(User).where(User.id == user.id).values(is_active=False))
        session.commit()


def _delete_user_in_new_session(
    session_factory: SessionFactory,
    user: User,
    pause: _Pause | None = None,
) -> None:
    """Delete a user in a session of its own, optionally stopping before the commit.

    The application deactivates users and never deletes them, but a
    deleted account is what a reset development database looks like to a
    browser still holding a token. The ``DELETE`` locks the user's row, and
    ``ON DELETE CASCADE`` deletes the user's refresh tokens within the same
    statement, locking their rows too, so a request held at ``pause`` holds
    those locks with every deletion not yet committed.

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


def _token_id(session_factory: SessionFactory, raw_token: str) -> uuid.UUID:
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

    The auth service imported ``generate_refresh_token`` by name, so the
    replacement goes into its namespace. Sign-in, refresh, and a password
    change all call it only after every check has passed and every lock
    the request takes, so a request stopped there holds those locks while
    the competing request starts: a sign-in holds the user's row, a
    refresh the user's row and its token's, and a password change the
    user's row and those of the tokens it revokes, having already written
    the new hash and the revocation.

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
    token's row locked and nothing written yet. A refresh has locked the
    user's row before it; a sign-out locks no user.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The pause the held request will stop at.
    """
    pause = _Pause()
    real_lookup = repository.get_refresh_token_by_hash_for_update

    def lookup_then_pause(session: Session, token_hash: str) -> RefreshToken | None:
        """Look the token up as usual, then stop the held request."""
        found_token = real_lookup(session, token_hash)
        pause.wait_here()
        return found_token

    monkeypatch.setattr(repository, "get_refresh_token_by_hash_for_update", lookup_then_pause)
    return pause


def _pause_after_the_owner_lookup(monkeypatch: pytest.MonkeyPatch) -> _Pause:
    """Make the held request stop just after refresh has found its token's user.

    Refresh reads the token's user through the repository module before it
    takes any lock, so a request stopped here holds no row lock: only the
    lock every read takes on the table, which blocks nothing but a change
    to the table itself. Its first row lock is the user's, which it asks
    for next.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The pause the held request will stop at.
    """
    pause = _Pause()
    real_lookup = repository.get_refresh_token_user_id_by_hash

    def lookup_then_pause(session: Session, token_hash: str) -> uuid.UUID | None:
        """Find the token's user as usual, then stop the held request."""
        found_user_id = real_lookup(session, token_hash)
        pause.wait_here()
        return found_user_id

    monkeypatch.setattr(repository, "get_refresh_token_user_id_by_hash", lookup_then_pause)
    return pause


def _pause_after_the_replacement_lookup(monkeypatch: pytest.MonkeyPatch) -> _Pause:
    """Make the held request stop just after a sign-out has found and locked a replacement.

    The service looks tokens up through the repository module, so replacing
    the function there reaches its calls. The held sign-out stops with the
    rotated token and its replacement both locked, no user locked, and
    nothing written yet.

    Args:
        monkeypatch: pytest's patching fixture; undoes the patch afterwards.

    Returns:
        The pause the held request will stop at.
    """
    pause = _Pause()
    real_lookup = repository.get_refresh_token_by_id_for_update

    def lookup_then_pause(session: Session, token_id: uuid.UUID) -> RefreshToken | None:
        """Look the token up as usual, then stop the held request."""
        found_token = real_lookup(session, token_id)
        pause.wait_here()
        return found_token

    monkeypatch.setattr(repository, "get_refresh_token_by_id_for_update", lookup_then_pause)
    return pause


def _pause_after_the_password_check(monkeypatch: pytest.MonkeyPatch) -> _Pause:
    """Make the held request stop just after a sign-in has checked its password.

    The auth service imported ``verify_login_password`` by name, so the
    replacement goes into its namespace. The held request stops with the
    check's result in hand, nothing written yet, and no row locked, since
    sign-in locks the account only once the password has passed. A wrong
    password and an unknown email reach this pause too: every sign-in runs
    the check, against a dummy hash when the email is unknown.

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


def _wait_until_the_held_request_pauses(pause: _Pause, held_future: Future[object]) -> None:
    """Return once the held request has reached its pause.

    The held request's future is checked while the test waits, so a held
    request that ends before its pause fails the test at once rather than
    after ``TIMEOUT_SECONDS``, with its own error if it raised one: a bug in
    the request, such as a ``NameError`` or a database error, then shows as
    itself instead of as a pause that never came.

    Args:
        pause: Where the held request stops.
        held_future: The held request, running in a thread of its own.

    Raises:
        Exception: The held request's own error, if it failed before its
            pause.
        pytest.fail.Exception: If the held request finished without
            reaching its pause, or didn't reach it within
            ``TIMEOUT_SECONDS``.
    """
    deadline = time.monotonic() + TIMEOUT_SECONDS

    while not pause.reached.wait(0.01):
        if held_future.done():
            # result() raises the request's own error; one that returned
            # went through without the pause.
            held_future.result()
            pytest.fail("the held request finished without reaching its pause", pytrace=False)

        if time.monotonic() >= deadline:
            pytest.fail("the held request never reached its pause", pytrace=False)


def _wait_until_a_request_waits_for_a_lock(
    engine: Engine, competing_future: Future[object]
) -> None:
    """Return once a statement in the race database is waiting for a lock.

    PostgreSQL lists every session in ``pg_stat_activity``, and a statement
    blocked by another transaction's lock shows ``wait_event_type = 'Lock'``.
    Only the running test's requests use that database, and the held one is
    paused in Python, not in the database, where it shows as idle in its
    transaction, so a waiting statement is the competing request's. A sleep
    would only guess: on a slow run the held request could be released
    before the competing one reached the lock, and the test would no longer
    race them. The polls run in autocommit mode, each in a transaction of
    its own, because PostgreSQL keeps showing a transaction the activity it
    read first: polled in one transaction, a request that started waiting
    after the first poll would never appear.

    Between two polls the competing request's future is checked. A request
    that waits for a lock can't finish while the held one holds it, so one
    that has finished never waited: it failed on its own, and its error is
    raised as it is, or it went through, as it does when the lock under
    test is missing. Either way the test fails at once rather than after
    ``TIMEOUT_SECONDS``.

    Args:
        engine: Engine for the race database.
        competing_future: The competing request, running in a thread of its
            own.

    Raises:
        Exception: The competing request's own error, if it failed before
            it waited for a lock.
        pytest.fail.Exception: If the competing request finished without
            waiting for a lock, or nothing waits within ``TIMEOUT_SECONDS``.
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

            if competing_future.done():
                # result() raises the request's own error; one that returned
                # went through without waiting.
                competing_future.result()
                pytest.fail(
                    "the competing request finished without waiting for a lock", pytrace=False
                )

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
    waits for a lock, so every run tests the same interleaving. A request
    that ends before its turn, the held one before its pause or the
    competing one before it waits, fails the race at once, with its own
    error if it raised one. The held request is released in every case,
    even when a step fails, and leaving the executors waits for both
    threads, so no request keeps a lock past the test.

    Args:
        engine: Engine for the race database, for the lock check.
        pause: Where the held request stops.
        held: The request that takes its locks first.
        competing: The request that must wait for them.

    Returns:
        The two requests' futures, held first. ``result()`` returns what a
        request returned, or raises the exception it raised.

    Raises:
        Exception: The held or the competing request's own error, if it
            failed before its turn.
        pytest.fail.Exception: If a request finished before its turn, or
            didn't get there within ``TIMEOUT_SECONDS``.
    """
    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix=HELD) as held_pool,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix=COMPETING) as competing_pool,
    ):
        held_future = held_pool.submit(held)

        try:
            _wait_until_the_held_request_pauses(pause, held_future)
            competing_future = competing_pool.submit(competing)
            _wait_until_a_request_waits_for_a_lock(engine, competing_future)
        finally:
            pause.released.set()

    return held_future, competing_future


class _RequestError(Exception):
    """The error a stand-in request raises on its own, as a bug in a request would."""


def _fail_on_its_own() -> None:
    """Stand in for a request that fails before its pause or its lock wait.

    Raises:
        _RequestError: Always, before it touches the database.
    """
    raise _RequestError("the request's own error")


def _finish_on_its_own() -> None:
    """Stand in for a request that goes through without its pause or its lock wait."""


# How a request can end before its turn in a race: the held one before its
# pause, or the competing one before it waits for a lock, by failing or by
# going through. Each case names the request that ends early, what it does,
# and what _race must raise at once: the request's own error, or a failure
# that says which request finished early.
REQUESTS_THAT_END_EARLY = [
    pytest.param(
        "held",
        _fail_on_its_own,
        _RequestError,
        "the request's own error",
        id="held-request-fails",
    ),
    pytest.param(
        "held",
        _finish_on_its_own,
        pytest.fail.Exception,
        "the held request finished without reaching its pause",
        id="held-request-finishes",
    ),
    pytest.param(
        "competing",
        _fail_on_its_own,
        _RequestError,
        "the request's own error",
        id="competing-request-fails",
    ),
    pytest.param(
        "competing",
        _finish_on_its_own,
        pytest.fail.Exception,
        "the competing request finished without waiting for a lock",
        id="competing-request-finishes",
    ),
]


@pytest.mark.parametrize(
    ("early_request", "end_early", "expected_error", "message"), REQUESTS_THAT_END_EARLY
)
def test_a_race_fails_at_once_with_the_cause_when_a_request_ends_early(
    early_request: str,
    end_early: Callable[[], None],
    expected_error: type[BaseException],
    message: str,
    race_engine: Engine,
) -> None:
    """A request that ends before its turn fails the race at once, and says why.

    Either the held request ends early, or it waits at its pause while the
    competing one does. The race must then fail with the request's own
    error when it raised one, so a bug inside a request shows as itself,
    and otherwise with a message that names the request that finished
    early, as a competing request does when the lock under test is
    missing. It must fail well within ``TIMEOUT_SECONDS``: before the fix
    the race waited the whole timeout, then blamed a pause or a lock that
    never came, and the request's own error was lost.
    """
    pause = _Pause()

    if early_request == "held":
        held, competing = end_early, _finish_on_its_own
    else:
        held, competing = pause.wait_here, end_early

    started = time.monotonic()

    with pytest.raises(expected_error, match=message):
        _race(race_engine, pause, held=held, competing=competing)

    assert time.monotonic() - started < TIMEOUT_SECONDS / 2


def test_the_race_sessions_are_built_by_the_applications_session_factory(
    race_engine: Engine,
    session_factory: SessionFactory,
) -> None:
    """Each request's session comes from ``SessionLocal``, bound to the race database.

    A session built by ``SessionLocal`` has every option the application's
    sessions have, one added later included, so the races run in sessions
    that behave as a request's do, instead of quietly copying some options
    and missing the next. ``sessionmaker`` builds a subclass of ``Session``
    of its own, its ``class_``, so a factory of these tests' own fails the
    check even when it is given the same options, as the one before the
    fix was. The session must still be bound to the race database, never
    to the engine ``SessionLocal`` holds, which stays bound to the
    development database.
    """
    with session_factory() as session:
        assert isinstance(session, SessionLocal.class_)
        assert session.get_bind() is race_engine


def test_a_second_refresh_with_the_same_cookie_waits_and_raises_the_alarm(
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: SessionFactory,
    committed_user: User,
) -> None:
    """Two refreshes sent together with one cookie never both rotate it.

    The first refresh is held after its checks, with the user's row and
    the token's locked. The second has to wait for the user's lock, then
    finds the token already rotated and raises the reuse alarm, which
    revokes every token of the user, including the one the first refresh
    just issued. ADR-0004 accepts that trade-off, and the web app must
    send one refresh at a time. Either lock alone keeps the two refreshes
    apart, since without the user's lock the second would wait for the
    token's; only without both would each read the token as unused,
    turning one cookie into two working sessions with no alarm. This test
    therefore can't see either lock on its own: the races with a sign-out
    pin the token's lock, and the reuse alarm's and the password change's
    races pin the user's.
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

    assert _count_tokens(session_factory, committed_user, is_unrevoked_only=True) == 0


def test_a_refresh_waits_for_a_sign_out_of_the_same_token_and_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: SessionFactory,
    committed_user: User,
) -> None:
    """A refresh that meets a sign-out of its token waits, then is refused.

    The sign-out is held after it has found and locked the token, before
    revoking it. A sign-out locks no user, so the refresh takes the user's
    lock and then has to wait for the token's; once the sign-out commits,
    the refresh reads the token as revoked, with no replacement, and is
    refused, so a refresh sent at the same moment can't revive the session
    that signed out. Without the token's lock the refresh would read the
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

    assert _count_tokens(session_factory, committed_user, is_unrevoked_only=False) == 1
    assert _count_tokens(session_factory, committed_user, is_unrevoked_only=True) == 0


def test_a_sign_out_that_waits_for_a_refresh_of_its_token_ends_the_new_session_too(
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: SessionFactory,
    committed_user: User,
) -> None:
    """A sign-out that meets a refresh of the same cookie also ends the token that refresh issues.

    The refresh is held after its checks, with the user's row and the
    token's locked, so the sign-out of the same token has to wait for the
    token's. Released, the refresh rotates the token and returns a
    replacement, which the browser may store after the sign-out has
    deleted the cookie. The sign-out must then revoke the replacement, so
    no token of that session works afterwards. Before the fix the sign-out
    found the token rotated and changed nothing, and the replacement kept
    the session alive.
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
    assert _count_tokens(session_factory, committed_user, is_unrevoked_only=True) == 0

    with pytest.raises(AuthenticationError):
        _refresh_in_new_session(session_factory, refreshed_tokens.refresh_token)


def test_a_refresh_of_the_replacement_waits_for_the_sign_out_revoking_it(
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: SessionFactory,
    committed_user: User,
) -> None:
    """A refresh of the replacement waits for the sign-out that is revoking it, then is refused.

    The cookie's token was already rotated, and the sign-out is held right
    after it has locked the replacement, with the cookie's token locked
    too. A refresh of that replacement, as the browser that received it
    would send, takes the user's lock, which a sign-out never holds, and
    has to wait for the replacement's; once the sign-out commits, the
    refresh finds the replacement revoked and is refused. Without the
    sign-out's lock on the replacement the refresh would rotate it while
    the sign-out was deciding, and its new token would outlive the
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

    assert _count_tokens(session_factory, committed_user, is_unrevoked_only=True) == 0


# Where the held refresh in the next two tests stops: after all its checks,
# or right after it has locked the token, holding the user's row and the
# token's at either point. A refresh that locked the token before the user
# would hold only the token at the second point, and it and the competing
# request would then wait for each other until PostgreSQL aborted one, so
# the second point is what pins the order of the two locks. That the lookup
# before them, which finds the token's user, takes no row lock a password
# change would wait for is pinned by
# test_a_password_change_never_waits_for_a_refresh_that_has_only_found_its_user.
# A FOR KEY SHARE lock there passes it, since no password change waits for
# that lock, although two refreshes of one cookie would then deadlock
# (R-114).
HELD_REFRESH_PAUSES = [
    pytest.param(_pause_before_issuing_tokens, id="held-before-issuing-tokens"),
    pytest.param(_pause_after_the_token_lookup, id="held-after-locking-the-token"),
]


@pytest.mark.parametrize("pause_held_refresh", HELD_REFRESH_PAUSES)
def test_the_reuse_alarm_revokes_the_token_of_a_refresh_still_in_flight(
    pause_held_refresh: Callable[[pytest.MonkeyPatch], _Pause],
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: SessionFactory,
    committed_user: User,
) -> None:
    """The reuse alarm also ends a session that a refresh is issuing at that moment.

    A thief refreshes with the replacement of a stolen token, and that
    refresh is held with the user's row and its token's locked. The real
    user then presents the stolen token, which was already rotated. That
    refresh has to wait for the user's lock until the held one commits,
    then finds the stolen token rotated and raises the alarm, which
    revokes the token the held refresh issued along with the rest, so the
    thief's new session ends with the others. Before the fix, when refresh
    took no user lock, the alarm's revocation saw only the tokens committed
    when it started, and the thief kept a session that went on refreshing.
    """
    raw_thief_token = _commit_refresh_token(session_factory, committed_user)
    raw_stolen_token = _commit_refresh_token(
        session_factory,
        committed_user,
        revoked_at=datetime.now(UTC),
        replaced_by_id=_token_id(session_factory, raw_thief_token),
    )
    pause = pause_held_refresh(monkeypatch)

    held_future, competing_future = _race(
        race_engine,
        pause,
        held=lambda: _refresh_in_new_session(session_factory, raw_thief_token),
        competing=lambda: _refresh_in_new_session(session_factory, raw_stolen_token),
    )

    thief_tokens = held_future.result()

    assert isinstance(thief_tokens, IssuedTokens)

    with pytest.raises(AuthenticationError):
        competing_future.result()

    assert _count_tokens(session_factory, committed_user, is_unrevoked_only=True) == 0

    with pytest.raises(AuthenticationError):
        _refresh_in_new_session(session_factory, thief_tokens.refresh_token)


@pytest.mark.parametrize("pause_held_refresh", HELD_REFRESH_PAUSES)
def test_a_password_change_revokes_the_token_of_a_refresh_still_in_flight(
    pause_held_refresh: Callable[[pytest.MonkeyPatch], _Pause],
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: SessionFactory,
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


def test_a_password_change_never_waits_for_a_refresh_that_has_only_found_its_user(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
    committed_user: User,
) -> None:
    """A refresh takes no lock before it locks the user, so a password change never waits for it.

    The refresh is held right after its first lookup, which reads only the
    token's user. A password change of the same user must then finish
    without waiting: ``lock_timeout`` turns any wait into an error. If that
    lookup locked the token, the held refresh would go on to wait for the
    user's lock while holding the token, and a password change, holding
    the user's lock, would wait for the token: a deadlock, which PostgreSQL
    ends by aborting one of them with an error. Released after the change,
    the refresh finds its token revoked and is refused.
    """
    raw_token = _commit_refresh_token(session_factory, committed_user)
    pause = _pause_after_the_owner_lookup(monkeypatch)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=HELD) as pool:
        held_refresh = pool.submit(_refresh_in_new_session, session_factory, raw_token)

        try:
            _wait_until_the_held_request_pauses(pause, held_refresh)

            with session_factory() as session:
                session.execute(text("SET LOCAL lock_timeout = '1s'"))
                signed_in_user = session.get(User, committed_user.id)
                assert signed_in_user is not None
                data = PasswordChange(current_password=PASSWORD, new_password=NEW_PASSWORD)

                service.change_password(session, signed_in_user, data)
        finally:
            pause.released.set()

    with pytest.raises(AuthenticationError):
        held_refresh.result()


def test_a_password_change_is_checked_against_a_change_committed_after_loading(
    session_factory: SessionFactory,
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
    session_factory: SessionFactory,
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
    assert _count_tokens(session_factory, committed_user, is_unrevoked_only=False) == 0


def test_a_password_change_is_refused_when_the_account_is_deleted_after_loading(
    session_factory: SessionFactory,
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
    session_factory: SessionFactory,
    committed_user: User,
) -> None:
    """A refresh is refused when its user is deleted while it waits.

    The application never deletes users, but a development database can
    be reset while a browser still holds a token. The deletion is held
    after its ``DELETE``, with the user's row locked and the user's tokens
    deleted and locked through the cascade, none of it committed. The
    refresh still finds the token's user, because the deletion isn't
    committed, and then has to wait for the user's lock. Once the deletion
    commits, the refresh finds neither the user nor the token, and must be
    refused rather than fail on the missing token, with the error every
    rejected token gets. No other test reaches this refusal, so the whole
    error is compared here, its status, code, message, and details, since
    the API sends all four in its response: a refusal with any of them its
    own would tell the token's holder that the account is gone.
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

    with pytest.raises(AuthenticationError) as exc_info:
        competing_future.result()

    error = exc_info.value

    assert error.status_code == 401
    assert error.code == ErrorCode.AUTHENTICATION_FAILED
    assert error.message == INVALID_TOKEN
    assert error.details == []


# What can happen to an account while a sign-in checks its password. Each
# runs in a session of its own and commits before the sign-in continues.
ACCOUNT_CHANGES_DURING_SIGN_IN = [
    pytest.param(_change_password_in_new_session, id="password-changed"),
    pytest.param(_deactivate_user_in_new_session, id="deactivated"),
    pytest.param(_delete_user_in_new_session, id="deleted"),
]


@pytest.mark.parametrize("change_account", ACCOUNT_CHANGES_DURING_SIGN_IN)
def test_a_sign_in_is_refused_when_the_account_changes_during_its_password_check(
    change_account: Callable[[SessionFactory, User], object],
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
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
            _wait_until_the_held_request_pauses(pause, sign_in)
            change_account(session_factory, committed_user)
        finally:
            pause.released.set()

    with pytest.raises(AuthenticationError):
        sign_in.result()


def test_a_password_change_revokes_the_session_of_a_sign_in_still_in_flight(
    monkeypatch: pytest.MonkeyPatch,
    race_engine: Engine,
    session_factory: SessionFactory,
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
    session_factory: SessionFactory,
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
            _wait_until_the_held_request_pauses(pause, first_sign_in)

            with session_factory() as session:
                session.execute(text("SET LOCAL lock_timeout = '1s'"))

                with pytest.raises(AuthenticationError):
                    service.login(session, committed_user.email, WRONG_PASSWORD)
        finally:
            pause.released.set()

    with pytest.raises(AuthenticationError):
        first_sign_in.result()
