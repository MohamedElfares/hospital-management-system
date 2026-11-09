"""Application factory: builds and configures the FastAPI application.

This module ties the platform pieces together. Logging is configured
first, so nothing written during startup is lost; the application then
gets the error handlers that produce the standard error body, the
middleware that gives every request an ID, and the routers.

``uv run fastapi dev app/main.py`` serves the module-level ``app`` built
at the bottom, and the production container will serve it the same way,
with ``fastapi run app/main.py`` (plan §16): the ``fastapi`` command looks
for a variable named ``app``. Importing this module therefore needs valid
settings, for two reasons: it builds ``app`` at import, and its imports
reach ``app.db.session``, which builds the engine from ``DATABASE_URL``.
"""

# The application class returned by the factory.
from fastapi import FastAPI

# Health check routes, kept outside /api/v1 so monitoring never follows the API's versioning.
from app.api.health import router as health_router

# Every module's routes, under the /api/v1 prefix.
from app.api.router import api_router

# Cached settings; supplies the log level.
from app.core.config import get_settings

# Attaches the four handlers that turn any failure into the standard error body.
from app.core.errors import register_exception_handlers

# Sets the root logger's level and line format, which every app module's log records use.
from app.core.logging import configure_logging

# Gives each request an ID, returns it in a header, and logs one line per request.
from app.core.logging import request_context_middleware


def create_app() -> FastAPI:
    """Build a fully configured application.

    A factory rather than only a module-level app, so each test can build
    its own application and replace a dependency on it, such as ``get_db``
    for the test's own session, without affecting any other test. The
    module-level ``app`` below comes from the same function.

    Logging is configured first, because until then Python's fallback
    writes only warnings and errors, as the bare message, so anything
    logged earlier would be lost or unformatted. The rest can come in any
    order: Starlette assembles the middleware stack, error handlers
    included, when the first request arrives. Order would start to matter
    with a second middleware, since the last one added runs first, and with
    routes whose paths overlap, such as the web app's catch-all route,
    which plan §8.7 registers after all the others.

    Returns:
        An application with logging configured, the error handlers
        registered, the request-context middleware installed, and the health
        and ``/api/v1`` routes included.

    Example:
        ``client = TestClient(create_app())``
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Hospital Management System API", version="0.1.0")
    register_exception_handlers(app)
    app.middleware("http")(request_context_middleware)
    app.include_router(health_router)
    app.include_router(api_router)

    return app


# Module-level so the fastapi command can find it; tests build their own with create_app().
app = create_app()
