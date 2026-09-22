"""Health check endpoints used by Render, Docker, and monitoring.

Two public routes answer two different questions. ``/health/live`` says the
process is running; ``/health/ready`` says it can serve requests, which
means the database answers. They sit outside ``/api/v1``, because a
monitoring system should not have to follow the API's versioning.
"""

# Attaches the dependency to the session parameter's type.
from typing import Annotated

# Groups these routes so the application can include them as one unit.
from fastapi import APIRouter

# Asks FastAPI to run get_db and pass the session to the route.
from fastapi import Depends

# Base class for the response model, which documents the body in OpenAPI.
from pydantic import BaseModel

# Builds the trivial "SELECT 1" statement used as the database ping.
from sqlalchemy import select

# Base class of every SQLAlchemy error, so one except covers connection failures.
from sqlalchemy.exc import SQLAlchemyError

# Type of the database session the readiness check receives.
from sqlalchemy.orm import Session

# Raised when the database can't be reached; the handler turns it into a 503.
from app.core.errors import ServiceUnavailableError

# Provides one database session for the request.
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


class HealthStatus(BaseModel):
    """Body of a successful health check.

    The response deliberately carries nothing else: these routes are public,
    so version numbers, hostnames, or database details would tell an
    attacker about the deployment for no operational gain.

    Attributes:
        status: Always ``"ok"``. A failing check answers with an error
            status code instead, never with a different value here.
    """

    status: str


@router.get(
    "/live",
    status_code=200,
    summary="Liveness check",
    response_model=HealthStatus,
)
def live() -> dict[str, str]:
    """Report that the process is running.

    This route touches nothing: no database, no settings, no dependencies.
    A failure therefore means the process itself is stuck or gone, and the
    right reaction is to restart the container. Because the database is not
    involved, a sleeping Neon instance never makes this route fail.

    Returns:
        ``{"status": "ok"}`` whenever the process can answer at all.
    """
    return {"status": "ok"}


@router.get(
    "/ready",
    status_code=200,
    summary="Readiness check",
    response_model=HealthStatus,
    responses={503: {"description": "The database is not reachable."}},
)
def ready(database: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    """Report that the application can serve requests right now.

    Render points its health check here (plan §16), so this decides whether
    a deployment receives traffic. The check runs ``SELECT 1``: the cheapest
    statement that still proves a connection can be taken from the pool and
    used. Only SQLAlchemy errors are treated as "not ready"; any other
    exception is a bug and becomes a 500, so real faults stay visible.

    Args:
        database: Session for this request, from the application's pool.

    Returns:
        ``{"status": "ok"}`` when the database answered.

    Raises:
        ServiceUnavailableError: If the database can't be reached. The
            handler turns it into a 503, and the driver's message stays in
            the log rather than in the response.
    """
    try:
        database.execute(select(1))
        return {"status": "ok"}
    except SQLAlchemyError as err:
        raise ServiceUnavailableError("The database is not reachable.") from err
