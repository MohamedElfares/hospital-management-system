"""Fixtures shared by every test in this folder.

pytest loads this file automatically, so tests use the fixtures below by
naming them as parameters and never import anything from here. The
application fixtures are built per test, so one test's dependency
overrides can never affect another; the engine and the migrations are done
once per run, because they are expensive and hold no per-test state.

Everything a test does through ``client`` or ``db_session`` happens inside
one transaction against the database named by ``TEST_DATABASE_URL``, and
that transaction is rolled back when the test ends. Tests therefore leave
nothing behind, and never touch the development database.
"""

# Environment of the migration subprocess, copied and overridden.
import os

# Runs "alembic upgrade head" as its own process.
import subprocess

# Path to the interpreter running the tests, so the subprocess uses the same one.
import sys

# Return type of a fixture that yields a value and then cleans up.
from collections.abc import Iterator

# Locates the backend folder, so Alembic runs where alembic.ini lives.
from pathlib import Path

# Test framework: the fixture decorator and the failure helper.
import pytest

# Type of the application the factory returns.
from fastapi import FastAPI

# Sends requests through the application without starting a server.
from fastapi.testclient import TestClient

# Type of the connection pool the test database fixtures share.
from sqlalchemy import Engine

# Builds that engine from the test database URL.
from sqlalchemy import create_engine

# Unit of work the tests share with the application's dependency.
from sqlalchemy.orm import Session

# Supplies the test database URL.
from app.core.config import get_settings

# The dependency the client fixture replaces with the test's session.
from app.db.session import get_db

# The application factory under test.
from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    """Build a fresh application for one test.

    Each test gets its own instance, so a dependency override or any other
    change made by one test cannot leak into the next one.

    Returns:
        A fully configured application, as the running server would use.
    """
    return create_app()


@pytest.fixture
def client(app: FastAPI, db_session: Session) -> TestClient:
    """Provide an HTTP client whose requests run in the test's transaction.

    The client sends requests through the whole stack, including the
    middleware and the exception handlers, without opening a network port.
    ``get_db`` is replaced by the test's own session, so a request writes
    into the same transaction the test can query afterwards, and everything
    is rolled back when the test ends. The override returns that session
    without closing it, because the fixture owns its lifecycle.

    A test that also asks for ``app`` gets the same instance this client is
    bound to, so it can override further dependencies itself.

    Args:
        app: The application built for this test.
        db_session: Session bound to the test's transaction.

    Returns:
        A client whose requests reach that application and that session.
    """
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    """Provide the engine for the test database, once per test run.

    Tests must never touch the development database, so the URL comes from
    ``TEST_DATABASE_URL`` alone and the run stops when it is missing rather
    than falling back to ``DATABASE_URL``. An engine is expensive to build
    and carries no per-test state, so one is shared by the whole session and
    disposed of at the end, closing its pooled connections.

    Yields:
        The engine connected to the test database.
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

    Tests run against the schema Alembic produces, not one built from the
    models, so a migration that drifts from the models is caught here rather
    than in production, where ``entrypoint.sh`` runs the same command. It
    runs in a subprocess with ``DATABASE_URL`` pointing at the test
    database, because ``migrations/env.py`` reads that setting: an in-process
    call would migrate the development database instead.
    """
    settings = get_settings()
    database_url = settings.test_database_url

    if database_url is None:
        pytest.fail("TEST_DATABASE_URL is not set", pytrace=False)

    environment = os.environ | {"DATABASE_URL": database_url}
    backend_dir = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(
            f"Alembic migration failed:\n{result.stderr}",
            pytrace=False,
        )


@pytest.fixture
def db_session(test_engine: Engine, apply_migrations: None) -> Iterator[Session]:
    """Provide a database session whose work is undone after the test.

    The fixture opens its own connection and starts a transaction on it, so
    everything the test writes lives inside that transaction and disappears
    when it is rolled back. ``join_transaction_mode="create_savepoint"``
    turns a service's ``commit()`` into the release of a savepoint instead
    of a real commit, so application code can commit normally and the outer
    rollback still erases it. Each test therefore starts from the same
    state, whatever the previous one wrote, without deleting rows by hand.

    Args:
        test_engine: Engine for the test database, shared by the run.
        apply_migrations: Not used directly; naming it makes the schema
            exist before the first session is opened.

    Yields:
        A session bound to the test's transaction.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()
