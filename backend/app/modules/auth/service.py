"""Business rules for signing in and out, sessions, password changes, and recognizing a user.

The service decides whether a sign-in succeeds and, if it does, issues the
session: a short-lived access token for the response body and a refresh
token for the cookie. It owns the transaction, so the new token row and the
user's sign-in time are committed together or not at all. It raises domain
errors from ``app.core.errors``, never HTTP errors, and returns plain data
that the router turns into a response and a cookie.

Refresh rotates the session: each refresh token works once, and using it
replaces it with a new one that keeps the original expiry. A token that is
presented again after being replaced means a copy exists, so every session
of that user is ended.

Signing out revokes only the refresh token of the device signing out, and
never fails, so signing out twice is harmless.

Changing a password requires the current one. It ends every session the
user has, on every device, and starts a new one for the device that made
the change.

On every later request, it turns the access token back into the user who
sent it, reading the account from the database so a deactivation takes
effect at once rather than when the token expires.

Every failed sign-in looks the same from outside: the same error, the same
message, and roughly the same time, so the API never reveals which emails
have accounts or which accounts are deactivated. A rejected access or
refresh token works the same way: one error and one message for every
reason.
"""

# Standard logging; records refresh token reuse as a security warning.
import logging

# Immutable record type for the tokens a sign-in or refresh returns.
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

# Error that the API turns into a 400 response; raised when a password change is refused.
from app.core.errors import BadRequestError

# Verifies the password, paying the same cost when the email matches no user.
from app.core.security import check_password

# Signs the access token returned in the response body.
from app.core.security import create_access_token

# Checks an access token's signature and expiry and returns the user id it carries.
from app.core.security import decode_access_token

# Creates the random refresh token sent in the cookie.
from app.core.security import generate_refresh_token

# Hashes the new password with Argon2id; only the hash is stored.
from app.core.security import hash_password

# Hashes the refresh token; only the hash is stored.
from app.core.security import hash_refresh_token

# Checks a password against the stored hash; confirms the current one and rejects reuse.
from app.core.security import verify_password

# Saves refresh token rows without committing.
from app.modules.auth import repository

# The refresh_tokens table's ORM model.
from app.modules.auth.models import RefreshToken

# Validated input for a password change: the current and the new password.
from app.modules.auth.schemas import PasswordChange

# The users table's ORM model; the type of the signed-in user.
from app.modules.users.models import User

# Users service lookup; other modules may not use the users repository.
from app.modules.users.service import get_user_by_email

# Users service lookup by id; loads the account an access token names.
from app.modules.users.service import get_user_by_id

# One message for every failure, so no reply hints at which check failed.
_INVALID_CREDENTIALS = "Incorrect email or password."

# Same text decode_access_token uses, so a missing or deactivated account
# looks exactly like an expired token. Tests pin both to one literal, so
# the two copies can't drift apart unnoticed.
_INVALID_TOKEN = "Invalid or expired token."

# Named after this module, so a reuse warning shows where it came from.
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssuedTokens:
    """The tokens issued by a sign-in or a refresh.

    Sign-in and refresh end the same way, with a new access token and a new
    refresh token, so they return the same type. This is internal data
    passed from the service to the router, not a response schema: the
    router puts the access token in the body and the refresh token in the
    cookie. It is frozen so neither token can be changed after it is issued.

    Attributes:
        access_token: The signed JWT for the ``Authorization: Bearer``
            header, returned in the response body.
        refresh_token: The raw refresh token. It goes only into the
            ``HttpOnly`` cookie, never into a response body or a log; the
            database holds only its hash.
    """

    access_token: str
    refresh_token: str


def _issue_tokens(
    session: Session,
    user: User,
    expires_at: datetime,
) -> tuple[IssuedTokens, RefreshToken]:
    """Create a new access token and refresh token for a user.

    This is the part sign-in and refresh share. A random refresh token is
    generated, and a row holding only its SHA-256 hash is added to the
    session; the raw value is returned once, for the cookie, and never
    stored. The access token is signed for the same user.

    The caller chooses the expiry, because the two cases differ: sign-in
    starts a new window of ``REFRESH_TOKEN_EXPIRE_DAYS``, while refresh
    keeps the old token's expiry, so refreshing never extends a session.
    Nothing is committed: each caller commits once at the end of its own
    use case, so a refresh can never save the new token without also
    revoking the old one. The row has no id until the session flushes.

    Args:
        session: The open database session. The new row is added to it
            but not committed.
        user: The user the tokens are for.
        expires_at: When the new refresh token stops working, timezone-aware
            UTC.

    Returns:
        The tokens to send to the client, and the new refresh token's row,
        which refresh links the revoked token to.
    """
    raw_refresh_token = generate_refresh_token()
    refresh_token_row = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh_token),
        expires_at=expires_at,
    )

    repository.add(session, refresh_token_row)

    # Keywords, because both fields are strings: swapped positions would put
    # the raw refresh token in the response body.
    issued_tokens = IssuedTokens(
        access_token=create_access_token(user.id),
        refresh_token=raw_refresh_token,
    )

    return issued_tokens, refresh_token_row


def login(session: Session, email: str, password: str) -> IssuedTokens:
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
    expires_at = now + timedelta(days=get_settings().refresh_token_expire_days)

    # The new row is only needed when a refresh links the old token to it.
    issued_tokens, _ = _issue_tokens(session=session, user=user, expires_at=expires_at)

    user.last_login_at = now

    # TODO(1.3): audit sign-ins, failed ones too (plan §8.6)

    session.commit()

    return issued_tokens


def refresh(session: Session, raw_refresh_token: str | None) -> IssuedTokens:
    """Exchange a refresh token for a new session, rotating the token.

    Each refresh token works once. A successful refresh revokes the
    presented token, links it to its replacement through
    ``replaced_by_id``, and issues a new access token and refresh token.
    The new refresh token keeps the old one's expiry, so refreshing never
    extends a session past the fixed window that began at sign-in. The
    presented row is locked while it is read, so two requests with the
    same token can't both rotate it.

    Only a rotated token presented again counts as reuse: it was already
    exchanged, so whoever sends it kept a copy, and the server can't tell
    the real user from a thief. Every token of that user is then revoked,
    a warning is logged without the token, and the revocation is committed
    before the error is raised. A token revoked any other way, by sign-out,
    a password change, deactivation, or an earlier alarm, has no
    replacement. It was ended on purpose, so it is refused like any other
    unusable token, with no alarm. This matters after a password change:
    the user's other devices still hold such tokens, and treating them as
    reuse would sign out the device that made the change.

    The web app calls this after a page reload, when the access token held
    in memory is gone, and whenever an access token expires. An expired
    token is only refused, with no alarm, since running out is normal. A
    pending password change doesn't block refresh, so the web app can
    restore the session after a reload and show the change-password screen.
    Refresh is not a sign-in, so ``last_login_at`` is left alone.

    Every failure raises the same error with the same message, so the
    reply never says which check failed.

    Args:
        session: The open database session. This function commits it on
            success, and when reuse is detected.
        raw_refresh_token: The cookie's value as the browser sent it, or
            None when there is no cookie. Never logged or stored.

    Returns:
        The new access token and refresh token.

    Raises:
        AuthenticationError: If the token is missing, unknown, revoked,
            or expired, or its owner is missing or deactivated.
    """
    if not raw_refresh_token:
        raise AuthenticationError(_INVALID_TOKEN)

    presented_token = repository.get_by_hash(session, hash_refresh_token(raw_refresh_token))

    if presented_token is None:
        raise AuthenticationError(_INVALID_TOKEN)

    now = datetime.now(UTC)

    if presented_token.revoked_at is not None:
        # Only a rotated token proves a copy exists. One revoked any other
        # way was ended on purpose, and after a password change the other
        # devices still hold such tokens: an alarm here would end the
        # session the change just started.
        if presented_token.replaced_by_id is None:
            raise AuthenticationError(_INVALID_TOKEN)

        # Checked before expiry so an old stolen token still raises the
        # alarm, and committed before raising because a failed request
        # would otherwise save nothing.
        logger.warning(
            "Refresh token reuse detected (user_id=%s, token_id=%s)",
            presented_token.user_id,
            presented_token.id,
        )
        repository.revoke_all_for_user(session, presented_token.user_id, now)

        # TODO(1.3): audit the reuse and the mass revocation (plan §8.6)

        session.commit()

        raise AuthenticationError(_INVALID_TOKEN)

    # No alarm and no revocation: tokens running out is normal.
    if presented_token.expires_at <= now:
        raise AuthenticationError(_INVALID_TOKEN)

    # Deactivation also revokes every token (plan §8.1); checking the account
    # here means a token that escaped that still can't start a new session.
    user = get_user_by_id(session, presented_token.user_id)

    if user is None or not user.is_active:
        raise AuthenticationError(_INVALID_TOKEN)

    # The old expiry, not a new one: refreshing never extends a session.
    issued_tokens, new_token_row = _issue_tokens(
        session,
        user,
        presented_token.expires_at,
    )

    # The new row gets its id on insert; flush so the link below isn't None.
    session.flush()

    presented_token.revoked_at = now
    presented_token.replaced_by_id = new_token_row.id

    session.commit()

    return issued_tokens


def logout(session: Session, user: User, raw_refresh_token: str | None) -> None:
    """Sign a user out on this device by revoking its refresh token.

    The refresh token from this browser's cookie is revoked, so the device
    can never refresh again. Only that one session ends: the user's other
    devices stay signed in. The token is revoked without a
    ``replaced_by_id``, which tells a sign-out apart from a rotation when
    the table is investigated later. The access token can't be revoked,
    since it is checked by signature and not looked up; the web app drops
    it from memory, and it expires within ``ACCESS_TOKEN_EXPIRE_MINUTES``.

    Sign-out never fails. A missing cookie, an unknown token, a token that
    is already revoked, and another user's token all leave the database
    unchanged, and the router still clears the cookie, so signing out twice
    gives the same result as signing out once.

    Args:
        session: The open database session. This function commits it only
            when a token is revoked.
        user: The signed-in user, from the access token. Only their own
            token can be revoked.
        raw_refresh_token: The cookie's value as the browser sent it, or
            None when there is no cookie. Never logged or stored.
    """
    if not raw_refresh_token:
        return

    presented_token = repository.get_by_hash(session, hash_refresh_token(raw_refresh_token))

    # Signing out ends only the caller's own session, so a stolen cookie
    # can't be used with another account to end someone else's. A revoked
    # token, even a rotated one, raises no reuse alarm here, unlike in
    # refresh: signing out can't start a session, so a copy gains nothing,
    # and a double-clicked sign-out must not end every device's session.
    if (
        presented_token is None
        or presented_token.user_id != user.id
        or presented_token.revoked_at is not None
    ):
        return

    presented_token.revoked_at = datetime.now(UTC)

    # TODO(1.3): audit sign-outs (plan §8.6)

    session.commit()


def get_authenticated_user(session: Session, access_token: str) -> User:
    """Return the active user an access token belongs to.

    Three checks run in order. The token is decoded first, which needs no
    database, so a forged, expired, or garbage token is rejected before it
    costs a query. Then the user it names is loaded. Finally, the account
    must exist and be active.

    The database is read on every call even though the token is signed,
    because a signature only proves who the user was when the token was
    issued. An access token stays valid for its whole lifetime, so without
    this read a deactivated user could keep working until it expired; with
    it, deactivation applies to their very next request. A missing account
    is possible too, for example after a development database is reset
    while a browser still holds a token.

    Every failure raises the same error with the same message, so a token
    holder can't tell a deactivated or missing account from an expired
    token. No timing parity is needed, unlike sign-in: reaching the
    database check requires a token the server signed, which an attacker
    can't produce. Nothing is written, so nothing is committed.

    This function deliberately ignores ``must_change_password``: the
    current-user endpoint must keep working while a password change is
    pending, so that gate is applied separately, on the routes it covers.

    Args:
        session: The open database session. Only read, never committed.
        access_token: The token from the ``Authorization: Bearer`` header,
            possibly empty or malformed.

    Returns:
        The user the token names, who exists and is active.

    Raises:
        AuthenticationError: If the token is invalid or expired, names no
            existing user, or names a deactivated user. The message is the
            same in every case.
    """
    user_id = decode_access_token(access_token)
    user = get_user_by_id(session, user_id)

    if user is None or not user.is_active:
        raise AuthenticationError(_INVALID_TOKEN)

    return user


def change_password(session: Session, user: User, data: PasswordChange) -> IssuedTokens:
    """Change the signed-in user's password and start a fresh session.

    The user must prove they know the current password, so a stolen access
    token alone can't take over the account. The new password must differ
    from the current one. That is checked with ``verify_password`` and not
    by comparing hashes, because Argon2 salts every hash, so two hashes of
    the same password never match. Both refusals are 400s, not 401s: the
    web app treats a 401 as an expired session and would sign the user out.

    On success the new hash replaces the old one and
    ``must_change_password`` is cleared, which lifts the forced-change
    gate. Every refresh token the user holds is revoked, ending their
    sessions on all devices, including any held by someone who knew the
    old password (plan §8.1). The caller gets a new session with a fresh
    refresh window, so the device that made the change stays signed in.
    Access tokens already issued keep working until they expire, within
    ``ACCESS_TOKEN_EXPIRE_MINUTES``. The sign-in time is left alone, since
    this isn't a sign-in. Everything is committed together.

    Args:
        session: The open database session. This function commits it.
        user: The signed-in user, from the access token.
        data: The current and new passwords, the new one already checked
            against the password rule. Neither is logged or stored.

    Returns:
        The new session's access token and refresh token.

    Raises:
        BadRequestError: If the current password is wrong, or the new
            password is the same as the current one. Nothing is saved.
    """
    current_password = data.current_password.get_secret_value()
    new_password = data.new_password.get_secret_value()

    if not verify_password(current_password, user.password_hash):
        raise BadRequestError("Current password is incorrect.")

    if verify_password(new_password, user.password_hash):
        raise BadRequestError("The new password must be different from the current one.")

    now = datetime.now(UTC)
    expires_at = now + timedelta(days=get_settings().refresh_token_expire_days)

    user.password_hash = hash_password(new_password)
    user.must_change_password = False

    # Revoke before issuing: the bulk UPDATE would otherwise also revoke the
    # new token, which autoflush has already written to the table.
    repository.revoke_all_for_user(session, user.id, now)

    issued_tokens, _ = _issue_tokens(session, user, expires_at)

    # TODO(1.3): audit password changes (plan §8.6)

    session.commit()

    return issued_tokens
