"""Database queries for user accounts.

The repository is the only layer that queries the ``users`` table. It never
commits: the service running the use case owns the transaction and commits
once, even when another module's service, such as ``auth``'s sign-in, is
the one running it. Other modules reach these queries only through the
users service, never by importing this module.
"""

# The UUID type of user ids; annotates the primary key being looked up.
import uuid

# Builds an EXISTS subquery; asks whether a matching row exists without loading it.
from sqlalchemy import exists

# Builds SELECT statements from the ORM model.
from sqlalchemy import select

# The database session the service passes in.
from sqlalchemy.orm import Session

# The role enum; the active-Admin check filters on Role.ADMIN.
from app.core.permissions import Role

# The users table's ORM model.
from app.modules.users.models import User


def get_user_by_email(session: Session, email: str) -> User | None:
    """Find the user with an exact email address.

    Emails are stored lowercase, and this function doesn't change the value
    it receives, so callers must pass an already normalized email, as
    ``UserCreate`` and the users service's ``get_user_by_email`` produce.
    The comparison is ``=``, never ``LIKE`` or ``ILIKE``: the ``Email`` rule
    accepts ``%`` and ``_`` before the @, and as wildcards they would let a
    typed pattern such as ``%@example.com`` find someone else's account.
    The unique constraint guarantees at most one match. Inactive users are
    returned too; filtering is the caller's decision.

    Args:
        session: The open database session.
        email: Lowercase email to look up.

    Returns:
        The matching user, or None if no account uses this email.
    """
    query = select(User).where(User.email == email)
    return session.scalar(query)


def get_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    """Find the user with a given primary key.

    ``Session.get`` is the primary-key lookup: it first checks the
    session's identity map, the objects this session has already loaded,
    and queries the database only when the user isn't there. Within one
    request that saves a query when the user was loaded earlier. Inactive
    users are returned too; filtering is the caller's decision.

    Args:
        session: The open database session.
        user_id: The primary key to look up.

    Returns:
        The matching user, or None if no account has this id.
    """
    return session.get(User, user_id)


def get_user_by_id_for_update(session: Session, user_id: uuid.UUID) -> User | None:
    """Find the user with a given primary key, lock the row, and read it fresh.

    The row is read with ``SELECT ... FOR NO KEY UPDATE``, so it stays
    locked until the caller's transaction commits or rolls back: another
    transaction that locks the row the same way, or updates it, waits until
    then. That is the lock an ``UPDATE`` of a user's ordinary columns takes,
    so it doesn't block inserting a row that refers to the user, such as a
    refresh token, whose foreign key check needs only a weaker share lock.

    Unlike ``get_user_by_id``, this always queries the database.
    ``populate_existing`` overwrites a copy the session already holds;
    without it, the session would return that copy with the values it had
    before the lock, even after another transaction changed the row.
    Inactive users are returned too; filtering is the caller's decision.

    Args:
        session: The open database session. The lock lasts until it
            commits or rolls back.
        user_id: The primary key to look up.

    Returns:
        The matching user, as the database holds it now, or None if no
        account has this id.
    """
    return session.get(
        User,
        user_id,
        with_for_update={"key_share": True},
        populate_existing=True,
    )


def exists_active_admin(session: Session) -> bool:
    """Tell whether at least one active Admin account exists.

    ``create-admin`` uses this to allow a new Admin only when nobody can
    sign in as one: on a fresh database, or after every Admin has been
    deactivated. Inactive Admins are ignored for that reason. ``EXISTS``
    lets PostgreSQL stop at the first match instead of loading rows, and
    the composite index on ``role`` and ``is_active`` covers both
    conditions.

    Args:
        session: The open database session.

    Returns:
        True if an Admin with ``is_active`` set exists, otherwise False.
    """
    query = select(exists().where((User.role == Role.ADMIN), (User.is_active.is_(True))))
    return bool(session.scalar(query))


def create_user(session: Session, user: User) -> None:
    """Add a new user to the session, to be inserted at the next flush.

    Nothing is written yet: the ``INSERT`` runs at the session's next flush,
    whether an explicit ``flush()``, the autoflush before its next query, or
    the commit. That is where a constraint violation such as a duplicate
    email surfaces, so the users service flushes right away and turns a
    duplicate into a ``ConflictError``.

    Args:
        session: The open database session.
        user: The new, unsaved user.
    """
    session.add(user)
