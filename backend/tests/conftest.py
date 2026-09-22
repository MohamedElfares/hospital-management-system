"""Fixtures shared by every test in this folder.

pytest loads this file automatically, so tests use the fixtures below by
naming them as parameters and never import anything from here. The
application fixtures are built per test, so one test's dependency
overrides can never affect another; the engine is built once per run,
because it is expensive and holds no per-test state.
"""

# Return type of a fixture that yields a value and then cleans up.
from collections.abc import Iterator

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

# Supplies the test database URL.
from app.core.config import get_settings

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
def client(app: FastAPI) -> TestClient:
    """Provide an HTTP client bound to this test's application.

    The client sends requests through the whole stack, including the
    middleware and the exception handlers, without opening a network port.
    It depends on ``app``, so a test that asks for both gets a client bound
    to the same application instance it can override dependencies on.

    Args:
        app: The application built for this test.

    Returns:
        A client whose requests reach that application.
    """
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
