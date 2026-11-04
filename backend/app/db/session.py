"""Database engine, session factory, and the per-request session dependency.

The engine is created once, when this module is first imported, from
``DATABASE_URL``, so importing it requires valid settings. Each request gets
its own session through ``get_db``, and the CLI opens one with
``SessionLocal``. Services own the transaction: they call ``commit()`` once
per use case, and this module never commits.
"""

# Abstract return type of a generator function such as get_db.
from collections.abc import Iterator

# Builds the engine and its connection pool from the database URL.
from sqlalchemy import create_engine

# Unit-of-work type that get_db yields to routes and services.
from sqlalchemy.orm import Session

# Factory that creates Session objects with the options below.
from sqlalchemy.orm import sessionmaker

# Cached application settings; supplies the database URL.
from app.core.config import get_settings

settings = get_settings()

# pool_pre_ping replaces connections that Neon dropped while its compute was
# suspended. The pool stays small because the app runs one worker and Neon's
# free plan limits connections. Forcing the session timezone to UTC makes
# PostgreSQL return timestamps in UTC, as the API contract requires. The
# connect timeout makes a request, and the readiness check, fail within
# seconds when the database is unreachable, instead of waiting for the
# operating system's TCP timeout.
engine = create_engine(
    url=settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args={"options": "-c timezone=utc", "connect_timeout": 5},
)

# expire_on_commit=False keeps loaded values after commit(), so a service can
# commit and then return the object for the router to serialize.
SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """Provide one database session for the duration of a request.

    FastAPI runs the code before ``yield`` before the route, and the rest
    after the response has been sent, or as soon as the route raises. It
    also reuses the value within a request, so the route and
    ``get_current_user`` share this one session. The ``with`` block closes
    the session in every case, and closing rolls back any transaction that
    wasn't committed, so a failed request never leaves partial changes
    behind. This function never commits; services decide when a use case is
    complete.

    Yields:
        A new ``Session`` bound to the application engine.

    Example:
        ``def list_patients(db: Annotated[Session, Depends(get_db)]): ...``
    """
    with SessionLocal() as session:
        yield session
