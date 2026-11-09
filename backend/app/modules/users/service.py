"""Business rules for creating and finding user accounts.

The service is the only place that decides whether a user may be created,
and the only way other modules, such as auth, can look users up, since
only this module may use the users repository. It checks the rules, hashes
the password, saves through the repository, and owns the transaction: a
use case that writes commits exactly once, at the end, and saves nothing
when it fails, while the lookups write nothing and leave the transaction
to their caller. It raises domain errors from ``app.core.errors``, never
HTTP errors, so the API and the ``create-admin`` command can each report
them in their own way.
"""

# The UUID type of user IDs; annotates the ID passed to the lookup.
import uuid

# Applies a type's validation outside a model; runs the Email rule on sign-in text.
from pydantic import TypeAdapter

# Raised when text fails the Email rule; such text can't belong to any account.
from pydantic import ValidationError

# Raised on flush when a constraint rejects the row; caught to report a duplicate email.
from sqlalchemy.exc import IntegrityError

# The database session passed in by the caller; this module commits it.
from sqlalchemy.orm import Session

# Business-rule error; the API turns it into 409 and the CLI prints its message.
from app.core.errors import ConflictError

# Role values; the first Admin's role is forced to ADMIN.
from app.core.permissions import Role

# Turns the plain password into the Argon2id hash that is stored.
from app.core.security import hash_password

# User queries as a module: the service reuses their names, and tests patch one of them.
from app.modules.users import repository

# The users table's ORM model; the new account is built from it.
from app.modules.users.models import User

# The email rule UserCreate stores addresses with; the lookup applies it to typed text.
from app.modules.users.schemas import Email

# Validated input for a new account.
from app.modules.users.schemas import UserCreate

# One message for both ways a duplicate is detected, the check before the
# insert and the unique constraint when two requests race, because to the
# caller they are the same conflict.
_EMAIL_TAKEN = "A user with this email already exists."

# Built once, because building a TypeAdapter compiles its validator, and
# every sign-in uses it.
_email_adapter = TypeAdapter(Email)


def create_user(session: Session, data: UserCreate, *, must_change_password: bool) -> User:
    """Create a user account and commit it.

    The email is checked first, so the usual duplicate gets a clear error
    without the cost of hashing. A deactivated account still holds its
    email, because users are never deleted. Two requests can still pass
    that check at the same moment; the database's unique constraint then
    rejects the second insert on flush, and that ``IntegrityError`` becomes
    the same ``ConflictError``, after a rollback that leaves the session
    usable. The rollback undoes everything since the last commit, which is
    safe only because this function owns the whole transaction: callers
    must not leave their own uncommitted changes in the same session. The
    plain password is read only here, to hash it, and is never stored.

    Admins will reuse this for staff accounts (IAM-5), passing
    ``must_change_password=True`` because those start with a temporary
    password.

    Args:
        session: The open database session. This function commits it.
        data: Validated input. The email is already normalized and
            lowercase.
        must_change_password: Whether the user must replace the password at
            the next sign-in.

    Returns:
        The saved user, with its ID and the database defaults loaded.

    Raises:
        ConflictError: If another account, active or not, already uses the
            email. Nothing is saved in that case.
    """
    if repository.get_user_by_email(session, data.email) is not None:
        raise ConflictError(_EMAIL_TAKEN)

    password_hash = hash_password(data.password.get_secret_value())
    user = User(
        email=data.email,
        password_hash=password_hash,
        full_name=data.full_name,
        role=data.role,
        must_change_password=must_change_password,
    )

    repository.create_user(session, user)

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
    exists for: no active Admin exists, so nobody can create one through
    the API. It works on a fresh database and after every Admin has been
    deactivated, and refuses otherwise; further Admins are created through
    the staff administration API (IAM-5). The role is forced to Admin
    whatever ``data.role`` says, and the password doesn't have to be
    changed, because the person chose it themselves.

    Two commands run at the same moment could both pass the Admin check
    and create two Admins. That is accepted: the command is run by hand,
    and rarely.

    Args:
        session: The open database session. This function commits it.
        data: Validated input for the new Admin.

    Returns:
        The saved Admin.

    Raises:
        ConflictError: If an active Admin already exists, or the email is
            taken. Nothing is saved in either case.
    """
    if repository.exists_active_admin(session):
        raise ConflictError("An active Admin already exists. Create more Admins through the API.")

    admin_data = data.model_copy(update={"role": Role.ADMIN})
    return create_user(session, admin_data, must_change_password=False)


def get_user_by_email(session: Session, email: str) -> User | None:
    """Find a user by email, however the address was typed.

    This is how other modules look users up, since only this module may use
    the users repository. Sign-in passes the raw form value, so the text
    first goes through the ``Email`` rule that ``UserCreate`` stores
    addresses with: ``" Admin@Example.COM "`` becomes ``admin@example.com``,
    an address typed with full-width letters or a decomposed accent
    becomes the form that was stored, and ``Eve <admin@example.com>``
    becomes the address alone. Matching the stored form exactly is
    what lets the repository use the unique index on ``email``.

    Text that isn't a valid address returns None without a query. No account
    can have such an email, because every stored one passed the same rule,
    and some of that text can't even be sent: PostgreSQL refuses a NUL
    character, and the query would fail instead of finding nobody. Sign-in
    then fails the way it does for an unknown email. A later email-validator
    release that rejected addresses it used to accept would lock their
    accounts out, so read its changelog before upgrading it.

    Inactive users are returned too. Deciding what deactivation means is
    the caller's job: sign-in must check the password before it looks at
    ``is_active``, so it needs the account either way. Nothing is written,
    so nothing is committed.

    Args:
        session: The open database session.
        email: The email as the user typed it.

    Returns:
        The matching user, active or not, or None if the text isn't a valid
        address or no user has that email.
    """
    try:
        normalized_email = _email_adapter.validate_python(email)
    except ValidationError:
        return None

    return repository.get_user_by_email(session, normalized_email)


def get_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    """Find a user by ID.

    This is how other modules load an account they already have an ID
    for, since only this module may use the users repository: auth uses it
    to load the user an access token names. A UUID has no case or spacing
    to normalize, so the ID is passed through unchanged.

    Inactive users are returned too. Deciding what deactivation means is
    the caller's job: auth rejects them, while staff administration must
    still find a deactivated account to show or reactivate it. Nothing is
    written, so nothing is committed.

    Args:
        session: The open database session.
        user_id: The ID of the user to load.

    Returns:
        The matching user, active or not, or None if no user has that ID.
    """
    return repository.get_user_by_id(session, user_id)


def get_user_by_id_for_update(session: Session, user_id: uuid.UUID) -> User | None:
    """Find a user by ID and lock the account's row until the transaction ends.

    Auth calls this before it issues, rotates, or revokes a user's refresh
    tokens: at sign-in once the password has passed, at refresh, and at a
    password change. Two such changes to one user's sessions, such as a
    refresh on one device and a password change on another, then run one
    after the other instead of overlapping. The row is read as the database holds it now,
    even if this session loaded the user earlier, so the caller sees a
    change that another request has just committed, such as a new password
    hash.

    Inactive users are returned too, as by ``get_user_by_id``. Nothing is
    written or committed: the lock ends when the caller's transaction does.

    Args:
        session: The open database session. The lock lasts until it
            commits or rolls back.
        user_id: The ID of the user to load and lock.

    Returns:
        The matching user, active or not, or None if no user has that ID.
    """
    return repository.get_user_by_id_for_update(session, user_id)
