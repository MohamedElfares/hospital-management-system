"""Business rules for creating user accounts.

The service is the only place that decides whether a user may be created.
It checks the rules, hashes the password, saves through the repository, and
owns the transaction: each use case ends with exactly one commit. It raises
domain errors from ``app.core.errors``, never HTTP errors, so the API and
the ``create-admin`` command can each report them in their own way.
"""

# Raised on flush when a database constraint rejects the row.
from sqlalchemy.exc import IntegrityError

# The database session passed in by the caller; this module commits it.
from sqlalchemy.orm import Session

# Business-rule error; the API turns it into 409 and the CLI prints its message.
from app.core.errors import ConflictError

# Role values; the first Admin's role is forced to ADMIN.
from app.core.permissions import Role

# Turns the plain password into the Argon2id hash that is stored.
from app.core.security import hash_password

# User queries; imported as a module so tests can replace one function.
from app.modules.users import repository

# The users table's ORM model.
from app.modules.users.models import User

# Validated input for a new account.
from app.modules.users.schemas import UserCreate

# One message for both ways a duplicate is detected, so callers can't tell
# the race case from the ordinary one.
_EMAIL_TAKEN = "A user with this email already exists."


def create_user(session: Session, data: UserCreate, *, must_change_password: bool) -> User:
    """Create a user account and commit it.

    The email is checked first, so the usual duplicate gets a clear error
    without the cost of hashing. Two requests can still pass that check at
    the same moment; the database's unique constraint then rejects the
    second insert on flush, and that ``IntegrityError`` becomes the same
    ``ConflictError``, after a rollback that leaves the session usable. The
    rollback undoes everything since the last commit, which is safe only
    because this function owns the whole transaction: callers must not
    leave their own uncommitted changes in the same session. The
    plain password is read only here, to hash it, and is never stored.

    Admins will reuse this for staff accounts (IAM-5), passing
    ``must_change_password=True`` because those start with a temporary
    password.

    Args:
        session: The open database session. This function commits it.
        data: Validated input. The email is already lowercase.
        must_change_password: Whether the user must replace the password at
            the next sign-in.

    Returns:
        The saved user, with its ID and database defaults set.

    Raises:
        ConflictError: If another account already uses the email. Nothing
            is saved in that case.
    """
    if repository.get_by_email(session, data.email) is not None:
        raise ConflictError(_EMAIL_TAKEN)

    password_hash = hash_password(data.password.get_secret_value())
    user = User(
        email=data.email,
        password_hash=password_hash,
        full_name=data.full_name,
        role=data.role,
        must_change_password=must_change_password,
    )

    repository.add(session, user)

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(_EMAIL_TAKEN) from exc

    # TODO(1.3): audit user creation

    session.commit()
    return user


def create_first_admin(session: Session, data: UserCreate) -> User:
    """Create the first Admin, for the ``create-admin`` command.

    The command skips sign-in, so its power is limited to the case it
    exists for: nobody can sign in as an Admin. It works on a fresh
    database and after every Admin has been deactivated, and refuses
    otherwise; further Admins are created through the API. The role is
    forced to Admin whatever ``data.role`` says, and the password doesn't
    have to be changed, because the person chose it themselves.

    Two commands run at the same moment could both pass the Admin check.
    That is accepted: the command is run by hand, once per environment.

    Args:
        session: The open database session. This function commits it.
        data: Validated input for the new Admin.

    Returns:
        The saved Admin.

    Raises:
        ConflictError: If an active Admin already exists, or the email is
            taken. Nothing is saved in either case.
    """
    if repository.active_admin_exists(session):
        raise ConflictError("An active Admin already exists. Create more Admins through the API.")

    admin_data = data.model_copy(update={"role": Role.ADMIN})
    return create_user(session, admin_data, must_change_password=False)
