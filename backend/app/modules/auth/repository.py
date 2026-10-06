"""Database queries for refresh tokens.

The repository is the only layer that queries the ``refresh_tokens`` table.
It never commits: the auth service owns the transaction, calls these
functions, and commits once per use case, so a sign-in saves its token and
the user's last sign-in time together or not at all. Other modules must go
through the auth service, never through this module.
"""

# The database session the service passes in.
from sqlalchemy.orm import Session

# The refresh_tokens table's ORM model.
from app.modules.auth.models import RefreshToken


def add(session: Session, token: RefreshToken) -> None:
    """Register a new refresh token with the session.

    Nothing is written yet: the row is inserted when the service flushes or
    commits, which is where constraint violations such as a duplicate hash
    or an unknown user surface.

    Args:
        session: The open database session.
        token: The new, unsaved token. It holds only the hash of the raw
            token, never the raw value.
    """
    session.add(token)
