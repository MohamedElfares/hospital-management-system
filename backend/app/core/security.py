"""Password hashing, access tokens, and the refresh token cookie.

Passwords are never stored. Each one is hashed with Argon2id through pwdlib:
a slow, memory-hard function with a random salt per password. A leaked
``users`` table therefore holds no passwords, only hashes that an attacker
must guess one at a time, at a high cost per guess.

After sign-in, requests carry a short-lived access token instead of the
password: an HS256 JSON Web Token signed with ``JWT_SECRET_KEY`` that names
the user and expires after ``ACCESS_TOKEN_EXPIRE_MINUTES``. The token proves
only who the caller is. Whether that user still exists, is active, and may
do what they ask is checked against the database on every request.

A refresh token, a random value that lasts ``REFRESH_TOKEN_EXPIRE_DAYS``,
gets the client a new access token without signing in again. It travels
only in an ``HttpOnly`` cookie. The database keeps a row for each token,
which is what lets a token be revoked, and the row holds only the token's
SHA-256 hash, so a leaked table can't be used to refresh a session.

The rest of the application calls the functions here and never imports
pwdlib or PyJWT, so the algorithms or their settings can change in this one
file. Only the tests import PyJWT, to build and read tokens directly.
"""

# Standard-library hashing; SHA-256 of refresh tokens for storage and lookup.
import hashlib

# Standard-library logging; records unsupported hashes without their contents.
import logging

# Cryptographically secure random values; refresh tokens and the dummy password.
import secrets

# UUID type of user IDs; the token's subject is parsed back into one.
import uuid

# UTC time zone; token timestamps are always in UTC.
from datetime import UTC

# Date and time type; gives the current time for the token's issued-at claim.
from datetime import datetime

# Length of time; adds the configured lifetime to the issue time to get the expiry.
from datetime import timedelta

# Type hint for a value of any type; the claim values mix strings and datetimes.
from typing import Any

# PyJWT; signs, verifies, and decodes the access tokens.
import jwt

# FastAPI's HTTP response; the refresh cookie is set on it and cleared from it.
from fastapi import Response

# pwdlib's hasher; recommended() gives Argon2id with safe default settings.
from pwdlib import PasswordHash

# Raised by pwdlib for a stored hash in a format it doesn't know; counted as a wrong password.
from pwdlib.exceptions import UnknownHashError

# Cached settings; the signing key, both token lifetimes, and the cookie's Secure flag.
from app.core.config import get_settings

# Error that the API turns into a 401 response; raised for any bad token.
from app.core.errors import AuthenticationError

logger = logging.getLogger(__name__)

# One hasher for the whole process, so every hash uses the same settings.
_password_hasher = PasswordHash.recommended()

# Fixed in code rather than configuration: the algorithm is a security
# decision, not a per-environment value, and decoding accepts only this one,
# so a token that names another algorithm (including "none") is rejected.
_JWT_ALGORITHM = "HS256"

# Public because the auth router reads the cookie by this name, in refresh
# and sign-out, while the helpers below set and clear it: one constant means
# a typo fails loudly instead of creating a cookie the router never finds.
REFRESH_COOKIE_NAME = "refresh_token"


def hash_password(password: str) -> str:
    """Hash a password for storage in ``users.password_hash``.

    The result is a self-describing Argon2id string such as
    ``$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>``: it carries the
    algorithm, the settings, and a new random salt, so hashing the same
    password twice gives two different strings that both verify. Hashing
    takes tens of milliseconds on purpose, which makes guessing slow for an
    attacker who has stolen the hashes. The password is used as given:
    rules such as a minimum length belong in the request schema.

    Args:
        password: The plain password. Never logged or stored.

    Returns:
        The encoded hash: 97 characters with the current settings, well
        within the 255 that ``users.password_hash`` allows.
    """
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a submitted password against a stored hash.

    pwdlib reads the algorithm, settings, and salt from ``password_hash``,
    hashes ``password`` the same way, and compares the results in constant
    time, so the comparison doesn't reveal how much of the hash matched.
    Passwords are compared exactly: case and surrounding spaces matter.

    A stored value in a format pwdlib doesn't know, such as a bcrypt hash,
    an empty string, or other text, counts as a failed match instead of an
    error. Sign-in then fails with the usual 401 rather than a 500, and a
    warning is logged so the bad row gets noticed. The warning is a fixed
    message, and the exception isn't logged: pwdlib's message is generic,
    and the stored value travels on the exception as its ``hash``
    attribute, which must stay out of the log. A damaged value that still
    looks like an Argon2 hash is different: pwdlib reports it as an
    ordinary mismatch, so it fails without a warning.

    Args:
        password: The password the user submitted.
        password_hash: The stored hash from ``users.password_hash``.

    Returns:
        True if the password matches the hash, and False if it doesn't or
        the stored value isn't a usable hash.
    """
    try:
        return _password_hasher.verify(password, password_hash)
    except UnknownHashError:
        logger.warning("Password hash uses an unknown or unsupported format")
        return False


# verify_login_password checks the password against this hash when the email
# matches no user, so an unknown email takes as long to reject as a wrong
# password and response times can't reveal which emails have accounts. It is
# built with hash_password, not pasted in, so it always has the same settings,
# and therefore the same cost, as real hashes.
_DUMMY_HASH = hash_password(secrets.token_urlsafe())


def create_access_token(user_id: uuid.UUID) -> str:
    """Create a signed access token for a user.

    The auth service calls this whenever it issues tokens: at sign-in, at
    each refresh, and after a password change. The token holds three claims
    and nothing else: ``sub`` (the user ID as a string), ``iat`` (when it
    was issued), and ``exp`` (when it expires, ``ACCESS_TOKEN_EXPIRE_MINUTES``
    later). Role, email, and permissions are left out on purpose: a token
    can't be changed once issued, so anything in it could go stale, and
    every request loads the user from the database instead. The token is
    signed, not encrypted, so anyone holding it can read the claims; that
    is why they hold only an opaque user ID and two timestamps.

    The short lifetime limits the damage of a stolen token. The client
    gets a new one through the refresh token instead of signing in again.

    Args:
        user_id: ID of the authenticated user.

    Returns:
        The encoded token, in the form ``header.payload.signature``. Never
        logged.
    """
    settings = get_settings()
    sub = str(user_id)
    iat = datetime.now(UTC)
    exp = iat + timedelta(minutes=settings.access_token_expire_minutes)
    claims: dict[str, Any] = {"sub": sub, "iat": iat, "exp": exp}

    return jwt.encode(
        claims, key=settings.jwt_secret_key.get_secret_value(), algorithm=_JWT_ALGORITHM
    )


def decode_access_token(token: str) -> uuid.UUID:
    """Verify an access token and return the ID of the user it names.

    The token is accepted only if it was signed with ``JWT_SECRET_KEY``
    using HS256, contains ``sub``, ``iat``, and ``exp``, hasn't expired, and
    wasn't issued in the future, and if ``sub`` is a string holding a UUID.
    PyJWT makes every check but the UUID one, which ``uuid.UUID`` makes. Claims
    are required explicitly because PyJWT checks ``exp`` only when it's
    present, and a token without one would never expire.

    Every failure raises the same error with the same message, so a caller
    can't tell which check failed. The token only proves identity: the
    caller must still load the user and reject one who no longer exists or
    has been deactivated.

    Args:
        token: The encoded token from the ``Authorization: Bearer`` header.

    Returns:
        The user ID from the ``sub`` claim.

    Raises:
        AuthenticationError: If the token is malformed, tampered with,
            signed with another key or algorithm, expired, issued in the
            future, or missing a required claim, or if its subject isn't a
            string holding a UUID.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            key=get_settings().jwt_secret_key.get_secret_value(),
            algorithms=[_JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError):
        # A bad token is ordinary client input, not a server fault, so
        # PyJWT's exception is left out of the chain rather than attached
        # to the error as its cause.
        raise AuthenticationError("Invalid or expired token.") from None


def generate_refresh_token() -> str:
    """Create a new random refresh token.

    The token is 32 bytes from the operating system's secure random source,
    256 bits that can't be guessed or derived from earlier tokens. It is
    encoded with URL-safe base64, so it fits in a cookie without escaping.
    It means nothing by itself: it is valid only while a stored row with its
    hash says so.

    Returns:
        The raw token, always 43 characters long. It is sent to the client
        once, in the cookie, and never stored or logged.
    """
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for storage in ``refresh_tokens.token_hash``.

    SHA-256 is fast and unsalted on purpose, unlike password hashing. The
    token is 256 random bits, so a fast hash can't be brute-forced, and
    without a salt the same token always gives the same hash, which is what
    lets a refresh find its row with an indexed lookup. Changing the
    algorithm would make every stored token unfindable and sign every user
    out.

    Args:
        token: The raw token from the client's cookie.

    Returns:
        The hash as 64 lowercase hexadecimal characters.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def verify_login_password(password: str, password_hash: str | None) -> bool:
    """Verify a sign-in password, taking the same time whether or not the user exists.

    When no user matched the email, the caller passes None. The password is
    then verified against ``_DUMMY_HASH`` so the slow Argon2 work still
    happens, and response times can't reveal which emails have accounts.
    The result of that check is ignored and False is returned explicitly,
    so a missing user can never sign in, whatever the dummy hash is.

    Sign-in is the one place that needs this. Where the user is already
    known, such as a password change, ``verify_password`` is the right call.

    Args:
        password: The password the user submitted.
        password_hash: The stored hash of the matching user, or None if no
            user has that email.

    Returns:
        True only if a user exists and the password matches their hash.
    """
    if password_hash is None:
        verify_password(password, _DUMMY_HASH)
        return False

    return verify_password(password, password_hash)


def set_refresh_cookie(response: Response, token: str) -> None:
    """Send the refresh token to the browser in its protected cookie.

    The auth router calls this with each new refresh token: at sign-in, at
    each refresh, and after a password change. Each cookie setting closes
    off one way to steal or misuse the token:

    - ``HttpOnly``: page scripts can't read it, so an XSS bug can't copy it.
    - ``SameSite=Strict``: the browser never sends it with requests started
      by another site, which blocks CSRF.
    - ``Path=/api/v1/auth``: it is sent only to the auth endpoints, not with
      every API call.
    - ``Secure`` in production: it is sent only over HTTPS. The other
      environments use plain HTTP, where the test client never returns a
      ``Secure`` cookie and browsers return one at most to ``localhost``,
      so the flag is off there.
    - ``Max-Age``: always the full ``REFRESH_TOKEN_EXPIRE_DAYS``. That
      matches the token at sign-in and after a password change, which each
      start a new window. A refreshed token keeps the old expiry, so its
      cookie outlives it; the server checks the real expiry, so ADR-0004
      accepts this as harmless.

    Args:
        response: The response that will carry the ``Set-Cookie`` header.
        token: The raw refresh token. It goes only into this cookie, never
            into a response body or a log.
    """
    settings = get_settings()
    max_age = settings.refresh_token_expire_days * 24 * 60 * 60

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="strict",
        path="/api/v1/auth",
        secure=settings.is_production,
        max_age=max_age,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Tell the browser to delete the refresh token cookie.

    Sign-out calls this so the browser stops sending a token that no longer
    works. The response carries a ``Set-Cookie`` header with an empty value
    and ``Max-Age=0``, which makes the browser drop the cookie at once.

    A browser only replaces a cookie with the same name and path, so these
    attributes must match ``set_refresh_cookie`` exactly: with any other
    path, the browser would treat this as a different cookie and keep the
    real one. The security flags match too, so the deleting header is held
    to the same rules as the one that created the cookie. No token is
    needed: a cookie is deleted by its name, never by its value.

    Args:
        response: The response that will carry the ``Set-Cookie`` header.
    """
    settings = get_settings()
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        samesite="strict",
        path="/api/v1/auth",
        secure=settings.is_production,
    )
