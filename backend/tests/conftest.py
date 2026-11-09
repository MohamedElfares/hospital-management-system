"""Fixtures shared by every test in this folder.

pytest loads this file automatically, so tests use the fixtures below by
naming them as parameters and never import anything from here. The
application fixtures are built per test, so a change one test makes to its
application, such as a dependency override, can never reach another. The
engine and the migrations are set up once per run: they hold no per-test
state, and one engine's pool spares each test the cost of opening a new
connection.

Everything a test does through ``client`` or ``db_session`` happens inside
one transaction against the database named by ``TEST_DATABASE_URL``, and
that transaction is rolled back when the test ends, so tests leave nothing
behind. The application's own engine stays bound to ``DATABASE_URL``, the
development database, and ``refuse_the_development_database`` refuses
every connection through it, so a test that bypasses these fixtures can't
reach that database either.
"""

# Environment of the migration subprocess, copied and overridden.
import os

# Runs "alembic upgrade head" as its own process.
import subprocess

# Path to the interpreter running the tests, so the subprocess uses the same one.
import sys

# Type of the stand-in for get_db that the get_test_db fixture returns.
from collections.abc import Callable

# Return type of a fixture that yields a value and then cleans up.
from collections.abc import Iterator

# Locates the backend folder, so Alembic runs where alembic.ini lives.
from pathlib import Path

# Return type of the listener that refuses connections: it always raises.
from typing import NoReturn

# Test framework: the fixture decorator and the failure helper.
import pytest

# Type of the application the factory returns.
from fastapi import FastAPI

# Sends requests through the application without starting a server.
from fastapi.testclient import TestClient

# Type of the engine the database fixtures share; it holds the connection pool.
from sqlalchemy import Engine

# Builds that engine from the test database URL.
from sqlalchemy import create_engine

# Attaches the listener that refuses connections to the application's engine.
from sqlalchemy import event

# Type of the session the fixtures hand to the tests and the code under test.
from sqlalchemy.orm import Session

# Supplies the test database URL.
from app.core.config import get_settings

# The application's session factory; db_session is built with its options.
from app.db.session import SessionLocal

# The application's engine, bound to DATABASE_URL; the run refuses its connections.
from app.db.session import engine as application_engine

# The dependency the client fixture replaces with the test's session.
from app.db.session import get_db

# The application factory, called once per test.
from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    """Build a fresh application for one test.

    Each test gets its own instance, so a change a test makes to it, such
    as a dependency override or an added route, can't leak into the next
    test. Tests take the application from this fixture instead of calling
    ``create_app`` themselves: ``create_app`` reconfigures logging with
    ``force=True``, which removes every handler on the root logger,
    ``caplog``'s among them. pytest attaches that handler again at the
    start of each test phase, so this fixture, which runs while the test is
    set up, leaves the test body's log records captured, while a call
    inside the test body leaves ``caplog`` empty from then on.

    Returns:
        A fully configured application, as the running server would use.
    """
    return create_app()


@pytest.fixture
def client(app: FastAPI, get_test_db: Callable[[], Iterator[Session]]) -> TestClient:
    """Provide an HTTP client whose requests run in the test's transaction.

    The client sends requests through the whole stack, including the
    middleware and the exception handlers, without opening a network port.
    ``get_db`` is replaced by ``get_test_db``, so each request gets the
    test's own session and ends it as the application ends a request's:
    what the test set up is committed first, and whatever the request
    didn't commit is rolled back when it ends. The test can then query
    what the request committed, and everything is rolled back when the
    test ends.

    An unexpected exception reaches the test as the exception itself rather
    than as the 500 response, because ``TestClient`` re-raises it by
    default; a test of the 500 body builds its own client with
    ``raise_server_exceptions=False``, as ``tests/test_errors.py`` does.

    A test that also asks for ``app`` gets the same instance this client is
    bound to, so it can override further dependencies itself.

    Args:
        app: The application built for this test.
        get_test_db: Stand-in for ``get_db`` that hands out the test's
            session.

    Returns:
        A client whose requests reach that application and that session.
    """
    app.dependency_overrides[get_db] = get_test_db
    return TestClient(app)


@pytest.fixture
def get_test_db(db_session: Session) -> Callable[[], Iterator[Session]]:
    """Provide a stand-in for ``get_db`` that hands out the test's session.

    The application opens a new session for each request in ``get_db``,
    and for each command with ``with SessionLocal() as session``, and
    closing it rolls back whatever wasn't committed. The stand-in ends the
    test's session the same way. It commits what the test set up, which
    would already be in the database before a real request, hands the
    session over, and rolls back once the request or command ends, failed
    or not. Only what the code under test committed is left, so a
    forgotten ``commit()`` fails the test that reads the result. Both the
    commit and the rollback stop at the test's savepoint, so the test's
    transaction stays open until ``db_session`` rolls all of it back.

    After the commit, the stand-in also expires every object the session
    holds. A new session starts empty and loads what it needs from the
    database, while this one still holds the test's objects, which its
    commit leaves as they are (``expire_on_commit=False``). Without the
    expiry, the code would read them as they are in memory: a time the
    test gave in Dubai time would reach a request as +04:00, where the
    database returns UTC.

    ``client`` installs the stand-in as the override for ``get_db``. A CLI
    test wraps it with ``contextlib.contextmanager`` and puts the result in
    place of ``SessionLocal``, so ``with SessionLocal() as session`` still
    works.

    Args:
        db_session: Session bound to the test's transaction.

    Returns:
        A generator function that yields ``db_session`` once.
    """

    def hand_out_the_test_session() -> Iterator[Session]:
        """Commit and expire the test's setup, yield the session, then roll back.

        Yields:
            The test's session, for one request or command.
        """
        db_session.commit()
        db_session.expire_all()
        try:
            yield db_session
        finally:
            db_session.rollback()

    return hand_out_the_test_session


def _refuse_the_connection(*_: object) -> NoReturn:
    """Refuse a connection that the application's engine is about to open.

    SQLAlchemy calls this ``do_connect`` listener with the dialect, the
    connection record, and the arguments it would connect with. None of
    them is needed, and the connect arguments hold the database password,
    so the listener neither keeps nor shows them. The error is a plain
    ``RuntimeError`` rather than a ``SQLAlchemyError``, so code that
    handles database errors, such as the readiness check, can't take it
    for an outage and answer as if the database were down.

    Raises:
        RuntimeError: Always, naming the rule and the fixtures to use
            instead.
    """
    raise RuntimeError(
        "Tests must not connect to the development database (DATABASE_URL). "
        "Use client, get_test_db, or db_session, which reach the test database."
    )


@pytest.fixture(scope="session", autouse=True)
def refuse_the_development_database() -> Iterator[None]:
    """Refuse every connection through the application's engine, for the whole run.

    The application's ``engine``, and the ``SessionLocal`` built on it,
    stay bound to ``DATABASE_URL`` while the tests run, and that names the
    development database. Tests reach a database only through engines
    built from ``TEST_DATABASE_URL``: ``client`` and the CLI tests hand the
    code under test the test's session through ``get_test_db``. A test
    that forgot to would write to the development database instead, and
    one that checks only a command's output would still pass. In CI that
    database is migrated before the tests run, so such a write would
    succeed there too.

    SQLAlchemy calls ``do_connect`` listeners before it opens a
    connection, so the listener refuses it before anything reaches the
    database, and a test that meets the error fails. Code that catches the
    error, as ``CliRunner`` does, still writes nothing. The fixture is
    session-scoped and autouse, so pytest sets it up before every other
    fixture of the run, the session-scoped ones included.

    Yields:
        Nothing; the listener is removed when the run ends.
    """
    event.listen(application_engine, "do_connect", _refuse_the_connection)
    yield
    event.remove(application_engine, "do_connect", _refuse_the_connection)


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    """Provide the engine for the test database, once per test run.

    Tests must never touch the development database, so the URL comes from
    ``TEST_DATABASE_URL`` alone, with no fallback to ``DATABASE_URL``. When
    it is missing, every test that needs the database errors with that
    message, while the tests that don't need one still run. One engine
    serves the whole run so that its pool keeps connections open between
    tests: building an engine is cheap, but opening a connection takes
    about 20 ms against the local database, where reusing a pooled one
    takes under 1 ms. Disposing of the engine at the end closes them.

    The pool and connection settings are the application engine's, from
    ``app/db/session.py``: PostgreSQL returns timestamps in UTC, as it does
    for the application, and an unreachable database fails within seconds.
    ``hide_parameters`` is deliberately left off, so a failing statement
    shows its values in the test output; test data holds no real secrets.

    Yields:
        The engine connected to the test database.

    Raises:
        pytest.fail.Exception: If ``TEST_DATABASE_URL`` isn't set.
    """
    settings = get_settings()
    database_url = settings.test_database_url

    if database_url is None:
        pytest.fail("TEST_DATABASE_URL is not set", pytrace=False)

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"options": "-c timezone=utc", "connect_timeout": 5},
    )

    yield engine

    engine.dispose()


@pytest.fixture(scope="session")
def apply_migrations() -> None:
    """Bring the test database's schema up to date, once per test run.

    Tests run against the schema the migrations build, not one created from
    the models, so a migration that leaves out a column or a constraint the
    code relies on fails the tests that use it instead of requests in
    production, and one that can't run at all fails here before the
    production container meets it: plan §16 has ``entrypoint.sh`` run the
    same ``alembic upgrade head`` at startup. Drift that no test exercises,
    such as a missing index, is left to ``alembic check`` in CI.

    Alembic runs in a subprocess with ``DATABASE_URL`` set to the test
    database, because ``migrations/env.py`` takes its URL from
    ``get_settings().database_url``. In this process that cached value is
    the development database's, so an in-process call would migrate the
    development database instead.

    Raises:
        pytest.fail.Exception: If ``TEST_DATABASE_URL`` isn't set, or the
            migration fails, with Alembic's error output in the message.
    """
    settings = get_settings()
    database_url = settings.test_database_url

    if database_url is None:
        pytest.fail("TEST_DATABASE_URL is not set", pytrace=False)

    environment = os.environ | {"DATABASE_URL": database_url}
    backend_dir = Path(__file__).resolve().parents[1]

    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    if upgrade.returncode != 0:
        pytest.fail(
            f"Alembic migration failed:\n{upgrade.stderr}",
            pytrace=False,
        )


@pytest.fixture
def db_session(test_engine: Engine, apply_migrations: None) -> Iterator[Session]:
    """Provide a database session whose work is undone after the test.

    The fixture opens its own connection and starts a transaction on it, so
    everything the test writes lives inside that transaction and disappears
    when it is rolled back. ``join_transaction_mode="create_savepoint"``
    runs the session inside a savepoint: a service's ``commit()`` releases
    the savepoint instead of committing, and its ``rollback()`` returns to
    it, so application code commits and rolls back as usual while the outer
    rollback still erases everything. Each test therefore starts with the
    same rows, whatever the previous one wrote, without deleting anything
    by hand. Sequences are the exception, because PostgreSQL never rolls
    them back.

    Requests and commands get the session through ``get_test_db``, which
    ends it as the application does. A service test that calls a service
    with this session directly gets no such boundary, so two things differ
    from a request. A service's ``rollback()`` also undoes what the test
    added since its last commit, so a test whose service rolls back
    commits its setup first, as an earlier request would have. And work a
    service flushed but never committed stays visible, so a service test
    sees a missing ``commit()`` only after calling ``db_session.rollback()``
    itself, as ``test_the_logout_revocation_is_committed`` does.

    The session is built by the application's ``SessionLocal``, bound to the
    test's connection instead of the engine, so it has the application's
    options. ``expire_on_commit=False`` keeps an object's values after a
    commit, so a service that commits and then returns an object hands the
    router the values it set, as it does in production. An option added to
    ``SessionLocal`` later reaches the tests too.

    Args:
        test_engine: Engine for the test database, shared by the run.
        apply_migrations: Not used directly; naming it makes the schema
            exist before the first session is opened.

    Yields:
        A session bound to the test's transaction.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()
