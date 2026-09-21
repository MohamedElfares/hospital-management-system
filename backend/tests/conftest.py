import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    """A freshly built application, one per test."""
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """An HTTP client bound to a freshly built application."""
    return TestClient(app)
