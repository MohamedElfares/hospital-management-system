"""Application factory: builds and configures the FastAPI application.

This module ties the platform pieces together. Logging is configured first,
so nothing written during startup is lost; the application then gets the
error handlers that produce the standard error body, the middleware that
gives every request an ID, and the routers. ``uv run fastapi dev
app/main.py`` and the production container both import the module-level
``app`` built at the bottom.
"""

# The application class returned by the factory.
from fastapi import FastAPI

# Health check routes, kept outside /api/v1 so monitoring never follows the API's versioning.
from app.api.health import router as health_router

# Cached settings; supplies the log level here, and more as the app grows.
from app.core.config import get_settings

# Attaches the four handlers that turn any failure into the standard error body.
from app.core.errors import register_exception_handlers

# Sets the level and format for every log record in the process.
from app.core.logging import configure_logging

# Gives each request an ID, returns it in a header, and logs one line per request.
from app.core.logging import request_context_middleware


def create_app() -> FastAPI:
    """Build a fully configured application.

    A factory rather than a module-level app: importing this module no
    longer requires valid settings, and tests can build a separate
    application per test, for example one bound to a test database. The
    order matters in one place only: logging is configured before anything
    else, because records written earlier would be dropped or unformatted.
    Handlers, middleware, and routers are registered before the server
    starts serving, and their relative order is not significant while there
    is a single middleware.

    Returns:
        An application with logging configured, the error handlers
        registered, the request-context middleware installed, and the health
        routes included.

    Example:
        ``client = TestClient(create_app())``
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Hospital Management System API", version="0.1.0")
    register_exception_handlers(app)
    app.middleware("http")(request_context_middleware)
    app.include_router(health_router)

    return app


app = create_app()
