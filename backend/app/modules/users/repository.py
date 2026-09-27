"""Database queries for user accounts.

The repository is the only layer that queries the ``users`` table. It never
commits: the users service owns the transaction, calls these functions, and
commits once per use case. Other modules must go through the users service,
never through this module.
"""

# Builds an EXISTS subquery; asks whether a matching row exists without loading it.
from sqlalchemy import exists

# Builds SELECT statements from the ORM model.
from sqlalchemy import select

# The database session the service passes in.
from sqlalchemy.orm import Session

# Role values used in query conditions.
from app.core.permissions import Role

# The users table's ORM model.
from app.modules.users.models import User


def get_by_email(session: Session, email: str) -> User | None:
    """Find the user with an exact email address.

    Emails are stored lowercase, and this function doesn't change the value
    it receives, so callers must pass an already normalized email, as
    ``UserCreate`` produces. The unique constraint guarantees at most one
    match.

    Args:
        session: The open database session.
        email: Lowercase email to look up.

    Returns:
        The matching user, or None if no account uses this email.
    """
    query = select(User).where(User.email == email)
    return session.scalar(query)


def active_admin_exists(session: Session) -> bool:
    """Tell whether at least one active Admin account exists.

    ``create-admin`` uses this to allow a new Admin only when nobody can
    sign in as one: on a fresh database, or after every Admin has been
    deactivated. Inactive Admins are ignored for that reason. ``EXISTS``
    lets PostgreSQL stop at the first match instead of loading rows.

    Args:
        session: The open database session.

    Returns:
        True if an Admin with ``is_active`` set exists, otherwise False.
    """
    query = select(exists().where((User.role == Role.ADMIN), (User.is_active.is_(True))))
    return bool(session.scalar(query))


def add(session: Session, user: User) -> None:
    """Register a new user with the session.

    Nothing is written yet: the row is inserted when the service flushes or
    commits, which is where constraint violations such as a duplicate email
    surface.

    Args:
        session: The open database session.
        user: The new, unsaved user.
    """
    session.add(user)
