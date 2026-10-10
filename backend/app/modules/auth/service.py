"""Business rules for signing in.

The service decides whether a sign-in succeeds and, if it does, issues the
session: a short-lived access token for the response body and a refresh
token for the cookie. It owns the transaction, so the new token row and the
user's sign-in time are committed together or not at all. It raises domain
errors from ``app.core.errors``, never HTTP errors, and returns plain data
that the router turns into a response and a cookie.

Every failed sign-in looks the same from outside: the same error, the same
message, and roughly the same time, so the API never reveals which emails
have accounts or which accounts are deactivated.
"""

# Immutable record type for the tokens a sign-in returns.
from dataclasses import dataclass

# UTC time zone; sign-in times and token expiries are always in UTC.
from datetime import UTC

# Current time for last_login_at and the refresh token's expiry.
from datetime import datetime

# Adds the configured refresh token lifetime to the sign-in time.
from datetime import timedelta

# The database session passed in by the caller; this module commits it.
from sqlalchemy.orm import Session

# Cached settings; supplies the refresh token lifetime.
from app.core.config import get_settings

# Error that the API turns into a 401 response; raised for every failed sign-in.
from app.core.errors import AuthenticationError

# Verifies the password, paying the same cost when the email matches no user.
from app.core.security import check_password

# Signs the access token returned in the response body.
from app.core.security import create_access_token

# Creates the random refresh token sent in the cookie.
from app.core.security import generate_refresh_token

# Hashes the refresh token; only the hash is stored.
from app.core.security import hash_refresh_token

# Saves refresh token rows without committing.
from app.modules.auth import repository

# The refresh_tokens table's ORM model.
from app.modules.auth.models import RefreshToken

# Users service lookup; other modules may not use the users repository.
from app.modules.users.service import get_user_by_email

# One message for every failure, so no reply hints at which check failed.
_INVALID_CREDENTIALS = "Incorrect email or password."


@dataclass(frozen=True)
class LoginResult:
    """The tokens issued by a successful sign-in.

    This is internal data passed from the service to the router, not a
    response schema: the router puts the access token in the body and the
    refresh token in the cookie. It is frozen so neither token can be
    changed after it is issued.

    Attributes:
        access_token: The signed JWT for the ``Authorization: Bearer``
            header, returned in the response body.
        refresh_token: The raw refresh token. It goes only into the
            ``HttpOnly`` cookie, never into a response body or a log; the
            database holds only its hash.
    """

    access_token: str
    refresh_token: str


def login(session: Session, email: str, password: str) -> LoginResult:
    """Sign a user in with their email and password.

    The email is matched ignoring case and surrounding spaces. The password
    is checked before the account's ``is_active`` flag, and every failure
    raises the same error with the same message: a wrong password, an
    unknown email, and a deactivated account are indistinguishable. Checking
    the password first means only someone who already knows it could learn
    that an account is deactivated, and an unknown email still pays the cost
    of a password check, so response times don't reveal which emails exist.

    On success, a new refresh token is stored as a hash with an expiry of
    ``REFRESH_TOKEN_EXPIRE_DAYS``, ``last_login_at`` is set, and both are
    committed in one transaction. Each sign-in issues its own refresh token,
    so a user can be signed in on several devices at once. A user who must
    change their password can still sign in; the API blocks their other
    requests until they do. A failed sign-in writes nothing.

    Args:
        session: The open database session. This function commits it on
            success.
        email: The email as typed in the sign-in form.
        password: The password as typed. Never logged or stored.

    Returns:
        The access token for the response body and the raw refresh token
        for the cookie.

    Raises:
        AuthenticationError: If the email matches no user, the password is
            wrong, or the account is deactivated. The message is the same
            in every case.
    """
    user = get_user_by_email(session, email)

    if not check_password(password, user.password_hash if user else None):
        raise AuthenticationError(_INVALID_CREDENTIALS)

    # check_password already rejected a missing user; testing for None again
    # lets the type checker know that user is set from here on.
    if user is None or not user.is_active:
        raise AuthenticationError(_INVALID_CREDENTIALS)

    # One timestamp for both writes, so the token's expiry and the recorded
    # sign-in time agree exactly.
    now = datetime.now(UTC)
    raw_token = generate_refresh_token()

    repository.add(
        session,
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=now + timedelta(days=get_settings().refresh_token_expire_days),
        ),
    )

    user.last_login_at = now
    session.commit()

    return LoginResult(
        access_token=create_access_token(user.id),
        refresh_token=raw_token,
    )
