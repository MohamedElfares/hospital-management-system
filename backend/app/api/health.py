"""Health check endpoints for the hosting platform and for monitoring.

Two routes answer two different questions. ``/health/live`` says the
process is running; ``/health/ready`` says it can serve requests, which
means the database answers. Plan §16 sets Render's health check path to
``/health/ready``. Both routes are public, as plan §11 lists them, so they
declare no authentication dependency. They sit outside ``/api/v1``,
because a monitoring system should not have to follow the API's
versioning.
"""

# Standard logging; records why a readiness check failed.
import logging

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

# The current request's ID, which ties the warning to the request's own log line.
from app.core.logging import request_id_var

# Provides one database session for the request.
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class HealthStatus(BaseModel):
    """Body of a successful health check.

    The response deliberately carries nothing else: these routes are public,
    so software versions, hostnames, or database details would tell an
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
def ready(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    """Report that the application can serve requests right now.

    Plan §16 sets Render's health check path to this route. Render sends a
    new deployment traffic only once this answers 200, and an instance that
    keeps failing it stops receiving traffic and is then restarted, so a
    failure here must mean that requests can't be served. The check runs
    ``SELECT 1``: the cheapest statement that still proves a connection can
    be taken from the pool and used. Only SQLAlchemy errors count as "not
    ready"; any other exception is a bug and becomes a 500, so real faults
    stay visible.

    Args:
        db: Session for this request, from the application's pool.

    Returns:
        ``{"status": "ok"}`` when the database answered.

    Raises:
        ServiceUnavailableError: If the database can't be reached. The
            handler turns it into a 503 with a fixed message, so the
            driver's message, which names the database host and user, stays
            out of this public response. A warning records it in the log
            instead, on one line, with the request ID.
    """
    try:
        db.execute(select(1))
        return {"status": "ok"}
    except SQLAlchemyError as exc:
        # The check repeats every few seconds while the database is down, so each failure
        # is one line without a traceback; %r keeps the driver's line breaks escaped.
        logger.warning("Readiness check failed (request_id=%s): %r", request_id_var.get(), exc)
        raise ServiceUnavailableError("The database is not reachable.") from exc
