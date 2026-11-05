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
of that user is ended. Sign-in, refresh, and a password change lock the
user's row before they issue or revoke tokens, so they take turns: no
token is ever issued while all of that user's tokens are being revoked,
where the revocation would miss it.

Signing out revokes only the refresh token of the device signing out, and
never fails, so signing out twice is harmless.

Changing a password requires the current one. It ends every session the
user has, on every device, and starts a new one for the device that made
the change.

On every later request, it turns the access token back into the user who
sent it, reading the account from the database so a deactivation takes
effect at once rather than when the token expires. A user who must still
replace a temporary password is then refused everywhere except the few
routes they need until they do, such as the password change itself.

Every failed sign-in looks the same from outside: the same error, the same
message, and roughly the same time, so the API never reveals which emails
have accounts or which accounts are deactivated. A rejected access or
refresh token works the same way: one error and one message for every
reason.
"""

# Standard logging; records refresh token reuse as a security warning.
import logging

# Immutable record type for the tokens a sign-in, refresh, or password change returns.
from dataclasses import dataclass

# UTC time zone; sign-in, expiry, and revocation times are always in UTC.
from datetime import UTC

# Current time for sign-in, expiry, and revocation times; also the type of an expiry.
from datetime import datetime

# Adds the configured refresh token lifetime to the current time when a session starts.
from datetime import timedelta

# The database session passed in by the caller; this module commits it.
from sqlalchemy.orm import Session

# Cached settings; supplies the refresh token lifetime.
from app.core.config import get_settings

# Error that the API turns into a 401 response; raised for a failed sign-in or a rejected token.
from app.core.errors import AuthenticationError

# Error that the API turns into a 400 response; raised when a password change is refused.
from app.core.errors import BadRequestError

# Machine-readable error codes; marks the 403 as a pending password change.
from app.core.errors import ErrorCode

# Error that the API turns into a 403 response; refuses a user with a temporary password.
from app.core.errors import PermissionDeniedError

# Signs the access token returned in the response body.
from app.core.security import create_access_token

# Checks an access token's signature and expiry and returns the user id it carries.
from app.core.security import decode_access_token

# Creates the random refresh token sent in the cookie.
from app.core.security import generate_refresh_token

# Hashes the new password with Argon2id; only the hash is stored.
from app.core.security import hash_password

# Hashes a refresh token; the hash is stored for a new token and finds a presented one.
from app.core.security import hash_refresh_token

# Verifies the password, paying the same cost when the email matches no user.
from app.core.security import verify_login_password

# Checks a password against the stored hash; confirms the current one and rejects reuse.
from app.core.security import verify_password

# Refresh token queries: finds, locks, saves, and revokes rows without committing.
from app.modules.auth import repository

# The refresh_tokens table's ORM model; each new token's row is built from it.
from app.modules.auth.models import RefreshToken

# Validated input for a password change: the current and the new password.
from app.modules.auth.schemas import PasswordChange

# The users table's ORM model; the type of the signed-in user.
from app.modules.users.models import User

# Users service lookup by email, for sign-in; other modules may not use the users repository.
from app.modules.users.service import get_user_by_email

# Users service lookup by id; loads the account an access token names.
from app.modules.users.service import get_user_by_id

# Users service lookup that locks the account's row, so session changes take turns.
from app.modules.users.service import get_user_by_id_for_update

# One message for every failed sign-in, so no reply hints at which check failed.
_INVALID_CREDENTIALS = "Incorrect email or password."

# Same text decode_access_token uses, so a missing or deactivated account
# looks exactly like an expired token; refresh uses it for every rejected
# refresh token too. Tests pin both copies to one literal, so they can't
# drift apart unnoticed.
_INVALID_TOKEN = "Invalid or expired token."

# Tells the user what to do next; the web app relies on the error code, not this text.
_PASSWORD_CHANGE_REQUIRED = "You must change your password before continuing."

# Named after this module, so a reuse warning shows where it came from.
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssuedTokens:
    """The tokens issued by a sign-in, a refresh, or a password change.

    All three end the same way, with a new access token and a new refresh
    token, so they return the same type. This is internal data passed from
    the service to the router, not a response schema: the router puts the
    access token in the body and the refresh token in the cookie. It is
    frozen so neither token can be changed after it is issued.

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

    This is the part sign-in, refresh, and a password change share. A
    random refresh token is generated, and a row holding only its SHA-256
    hash is added to the session; the raw value is returned once, for the
    cookie, and never stored. The access token is signed for the same user.

    The caller chooses the expiry, because the cases differ: sign-in and a
    password change start a new window of ``REFRESH_TOKEN_EXPIRE_DAYS``,
    while refresh keeps the old token's expiry, so refreshing never extends
    a session. Nothing is committed: each caller commits once at the end of
    its own use case, so a refresh can never save the new token without
    also revoking the old one. The row has no id until the session flushes.

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

    repository.create_refresh_token(session, refresh_token_row)

    # Keywords, because both fields are strings: swapped positions would put
    # the raw refresh token in the response body.
    issued_tokens = IssuedTokens(
        access_token=create_access_token(user.id),
        refresh_token=raw_refresh_token,
    )

    return issued_tokens, refresh_token_row


def login(session: Session, email: str, password: str) -> IssuedTokens:
    """Sign a user in with their email and password.

    The email is matched in the form account creation stored it, so case,
    surrounding spaces, and email-validator's other rewrites don't matter,
    and text that isn't an address fails like an unknown email. The password
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

    Once the password has passed, the account's row is locked, as refresh
    and a password change lock it, and read again before the session is
    issued. If the account changed after it was first read, because its
    password was changed or it was deactivated or deleted, the sign-in fails
    like any other, so the old password can't start a session that the
    password change should have ended. A password change that comes later
    waits for the lock and then revokes this session with the rest. Only a
    correct password for an active account takes the lock. A wrong one
    never does, so failed attempts on an existing account never wait for
    each other; if they did, the wait would reveal that the account exists,
    since attempts on an unknown email never wait.

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
            wrong, or the account is deactivated, or if the account changed
            between being read and being locked. The message is the same in
            every case.
    """
    user = get_user_by_email(session, email)

    if not verify_login_password(password, user.password_hash if user else None):
        raise AuthenticationError(_INVALID_CREDENTIALS)

    # verify_login_password already rejected a missing user; testing for None again
    # lets the type checker know that user is set from here on.
    if user is None or not user.is_active:
        raise AuthenticationError(_INVALID_CREDENTIALS)

    # Lock and reread the account only now, so failed sign-ins never wait for
    # each other. The hash the password passed against must still be the
    # stored one: if it changed, the password did.
    verified_password_hash = user.password_hash
    user = get_user_by_id_for_update(session, user.id)

    if user is None or user.password_hash != verified_password_hash or not user.is_active:
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
    extends a session past the fixed window that began when the session
    started, at sign-in or at a password change.

    Two row locks keep concurrent requests apart, always taken in the same
    order: the user's row, then the token's. The reuse alarm and a password
    change hold the same user lock while they revoke all of the user's
    tokens, so neither can run while this refresh is between its locks and
    its commit, and the token it issues can't escape them. Two refreshes
    with the same cookie run one after the other too, and the second finds
    the token rotated and raises the alarm, which ADR-0004 accepts. The
    token's own lock does the same for a sign-out of that token. Taking
    them in the other order would let the alarm and a refresh of another
    token wait for each other, which PostgreSQL ends by aborting one of
    them.

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
    in memory is gone, and whenever an access token expires. A token that
    simply ran out is refused with no alarm, since running out is normal;
    a rotated one raises the alarm however old it is, because reuse is
    checked first. A pending password change doesn't block refresh, so the
    web app can restore the session after a reload and show the
    change-password screen. Refresh is not a sign-in, so ``last_login_at``
    is left alone.

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
        AuthenticationError: If the token is missing, unknown, revoked, or
            expired, or its owner is missing or deactivated. The message is
            the same in every case. A rotated token presented again first
            ends every session of its user, and that is committed.
    """
    if not raw_refresh_token:
        raise AuthenticationError(_INVALID_TOKEN)

    token_hash = hash_refresh_token(raw_refresh_token)

    # The user's row first, then the token's, the order a password change
    # locks in too. A token's user never changes, so it can be read before
    # any lock is held.
    user_id = repository.get_refresh_token_user_id_by_hash(session, token_hash)

    if user_id is None:
        raise AuthenticationError(_INVALID_TOKEN)

    user = get_user_by_id_for_update(session, user_id)
    presented_token = repository.get_refresh_token_by_hash(session, token_hash)

    # Deleting the user before its lock was granted deletes the token too.
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
        repository.revoke_all_refresh_tokens_for_user(session, presented_token.user_id, now)

        # TODO(1.3): audit the reuse and the mass revocation (plan §8.6)

        session.commit()

        raise AuthenticationError(_INVALID_TOKEN)

    # No alarm and no revocation: tokens running out is normal.
    if presented_token.expires_at <= now:
        raise AuthenticationError(_INVALID_TOKEN)

    # Deactivation also revokes every token (plan §8.1); checking the account
    # here means a token that escaped that still can't start a new session.
    if user is None or not user.is_active:
        raise AuthenticationError(_INVALID_TOKEN)

    # The old expiry, not a new one: refreshing never extends a session.
    issued_tokens, new_token_row = _issue_tokens(
        session,
        user,
        presented_token.expires_at,
    )

    # The new row's id is generated when it is flushed; flush now so the
    # link below isn't None.
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
    ``replaced_by_id``, so if it comes back, refresh refuses it quietly,
    without the reuse alarm, and the table tells a sign-out apart from a
    rotation. The access token can't be revoked, since it is checked by
    signature and not looked up; the web app drops it from memory, and it
    expires within ``ACCESS_TOKEN_EXPIRE_MINUTES``.

    Sign-out never fails. A missing cookie, an unknown token, a token that
    is already revoked, and another user's token all leave the database
    unchanged, and the router still clears the cookie, so signing out twice
    gives the same result as signing out once.

    The token's row is locked while it is read, so a sign-out and a refresh
    of the same token run one after the other. A refresh that comes second
    finds the token revoked and is refused. One that comes first has
    already rotated the token, so the sign-out changes nothing, and the new
    token that refresh issued keeps working.

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

    presented_token = repository.get_refresh_token_by_hash(
        session, hash_refresh_token(raw_refresh_token)
    )

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

    It works in three steps. The token is decoded first, which needs no
    database, so a forged, expired, or garbage token is rejected before it
    costs a query. Then the user it names is loaded. Finally, the account
    must exist and be active.

    The database is read on every request even though the token is signed,
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
    pending. The gate is ``ensure_password_change_not_pending``, which
    routes get through ``CurrentUser``, the default for any route that
    needs a signed-in user; only ``/auth/me``, ``/auth/logout``, and
    ``/auth/change-password`` skip it.

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


def ensure_password_change_not_pending(user: User) -> None:
    """Refuse a user who must still replace a temporary password.

    A new account, or one whose password an administrator reset, gets a
    temporary password and ``must_change_password`` set. Until the user
    chooses their own password, every route that needs a signed-in user
    refuses them, so a temporary password that was shared or written down
    can't be used for real work. The exceptions are the routes they still
    need (plan §8.1): ``/auth/me``, ``/auth/logout``, and
    ``/auth/change-password`` skip this check, and ``/auth/refresh`` needs
    no access token at all.

    The check runs after the access token and the account have been
    accepted, so a bad token or a deactivated account still gets a 401;
    only a valid, active user can get this 403. It is a 403, not a 401,
    because the user is signed in: the web app reads the code and shows the
    change-password screen instead of signing them out.

    Args:
        user: The active, signed-in user.

    Raises:
        PermissionDeniedError: With code ``PASSWORD_CHANGE_REQUIRED`` if
            ``must_change_password`` is set.
    """
    if user.must_change_password:
        raise PermissionDeniedError(
            _PASSWORD_CHANGE_REQUIRED,
            code=ErrorCode.PASSWORD_CHANGE_REQUIRED,
        )


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
    gate. Every refresh token the user still holds is revoked, ending their
    sessions on all devices, including any held by someone who knew the
    old password (plan §8.1). The caller gets a new session with a fresh
    refresh window, so the device that made the change stays signed in.
    Access tokens already issued keep working until they expire, within
    ``ACCESS_TOKEN_EXPIRE_MINUTES``. The sign-in time is left alone, since
    this isn't a sign-in. Everything is committed together.

    The user's row is locked before anything is checked, as refresh and a
    sign-in lock it, so neither a refresh on another device nor a sign-in
    with the old password can slip a new token past the revocation. The
    lock also reloads ``user``, so the current password is checked against
    the hash as it is now, even if another password change committed after
    this request loaded the account.

    Args:
        session: The open database session. This function commits it.
        user: The signed-in user, from the access token, loaded in this
            session.
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

    # The same lock refresh and sign-in take, so they run in turn (see refresh).
    # It reloads user in place, because user belongs to this session.
    get_user_by_id_for_update(session, user.id)

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
    repository.revoke_all_refresh_tokens_for_user(session, user.id, now)

    issued_tokens, _ = _issue_tokens(session, user, expires_at)

    # TODO(1.3): audit password changes (plan §8.6)

    session.commit()

    return issued_tokens
