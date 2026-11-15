"""HTTP routes for signing in and out, sessions, password changes, and the signed-in user.

The router handles HTTP only: it reads the request, calls one service
function or dependency, and turns the result into a response. Every rule
about who may sign in, and who counts as signed in, lives in the service,
whose refusals come back as domain errors. FastAPI raises its own errors
for a missing bearer token or an invalid body, and the exception handlers
turn both kinds into the standard error body.

Signing in is Public, since it is how a caller becomes authenticated.
Refresh is Public with the refresh cookie: it must work when the access
token has expired or is gone. Sign-out, changing the password, and the
current-user route are Authenticated: they need a valid access token. Of
the routes that need one, they are the only ones that stay open while a
password change is pending, since a user with a temporary password needs
them to see the change-password screen, change it, or sign out. Sign-in
and refresh take no access token, so the gate never applies to them.

FastAPI makes each route's docstring the route's description in the
OpenAPI schema, so Swagger UI shows it in full.
"""

# Attaches FastAPI's dependency and cookie declarations to parameter types.
from typing import Annotated

# Groups these routes under /auth so the API router can include them as one unit.
from fastapi import APIRouter

# Reads the refresh token from the request's cookie instead of the body.
from fastapi import Cookie

# Asks FastAPI to build the form and the database session for the route.
from fastapi import Depends

# A response FastAPI merges into the one it sends; the routes set or clear the cookie on it.
from fastapi import Response

# Type of the database session passed to the service.
from sqlalchemy.orm import Session

# The signed-in user, without the gate: these routes stay open while a password change is due.
from app.api.deps import CurrentUserAllowingPasswordChange

# The refresh cookie's name, shared with set_refresh_cookie so reading and writing agree.
from app.core.security import REFRESH_COOKIE_NAME

# Deletes the refresh cookie with the same name, path, and flags it was set with.
from app.core.security import clear_refresh_cookie

# Tells every cache not to store a response that carries tokens, as RFC 6749 §5.1 requires.
from app.core.security import forbid_caching

# Writes the refresh token into its HttpOnly cookie with every security flag.
from app.core.security import set_refresh_cookie

# Provides one database session for the request.
from app.db.session import get_db

# Auth use cases; imported as a module because the routes share their names, such as login.
from app.modules.auth import service

# The sign-in form: the OAuth2 password form, with the email in "username", and length limits.
from app.modules.auth.schemas import LoginForm

# Body of a password change: the current and the new password, as JSON.
from app.modules.auth.schemas import PasswordChange

# Body of a sign-in, a refresh, or a password change: the access token and its type.
from app.modules.auth.schemas import TokenResponse

# The users table's ORM model; what the current-user route returns.
from app.modules.users.models import User

# The public fields of a user; filters what the current-user route sends.
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    summary="Sign in",
    response_model=TokenResponse,
    responses={401: {"description": "Incorrect email or password."}},
)
def login(
    form: Annotated[LoginForm, Depends()],
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Sign in with an email and password. Public.

    The request is a form with the email in the ``username`` field, as the
    OAuth2 password flow requires, so Swagger UI's Authorize button works.
    That flow sends ``application/x-www-form-urlencoded``; a JSON body is
    rejected with a 422, and so is an email longer than 255 characters or
    a password longer than 128, which no account can have. On success, the
    access token goes in the body and the refresh token goes only into the
    ``HttpOnly`` cookie, so page scripts can never read it, and the
    response tells every cache not to store it. Every failed sign-in,
    whether the email is unknown, the password is wrong, or the account is
    deactivated, gets the same 401 and no cookie.

    Args:
        form: The sign-in form; ``username`` holds the email.
        response: Holds the headers FastAPI adds to the response; the
            refresh cookie and the headers that forbid caching are set on
            it.
        db: Session for this request; the service commits it on success.

    Returns:
        The access token, with ``token_type`` ``"bearer"``.

    Raises:
        AuthenticationError: From the service, for any failed sign-in. The
            handler turns it into a 401 with code ``AUTHENTICATION_FAILED``.
    """
    issued_tokens = service.login(db, form.username, form.password)
    set_refresh_cookie(response, issued_tokens.refresh_token)
    forbid_caching(response)

    return TokenResponse(access_token=issued_tokens.access_token)


@router.post(
    "/refresh",
    summary="Refresh the session",
    response_model=TokenResponse,
    responses={
        401: {
            "description": (
                "Missing, invalid, expired, revoked, or reused refresh token, "
                "or the account is deactivated."
            )
        }
    },
)
def refresh(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> TokenResponse:
    """Exchange the refresh cookie for a new access token. Public, with the cookie.

    The web app will call this after a page reload, when the access token
    it kept in memory is gone, and when a request gets a 401 because the
    access token expired (plan §8.1), so it needs no ``Authorization``
    header. The browser sends the cookie by itself, only to
    ``/api/v1/auth`` paths. On success the new access token goes in the
    body and the new refresh token replaces the old one in the
    ``HttpOnly`` cookie, and the response tells every cache not to store
    it, as at sign-in. It is a ``POST`` because it changes state, and
    ``SameSite=Strict`` keeps other sites from sending the cookie.

    The cookie defaults to None, so a request without it reaches the
    service and gets the standard 401 rather than a 422 validation error.
    A failed refresh sets no cookie: the error handler builds a new
    response, so nothing set here would survive.

    Args:
        response: Holds the headers FastAPI adds to the response; the new
            refresh cookie and the headers that forbid caching are set on
            it.
        db: Session for this request; the service commits it on success,
            and when it raises the reuse alarm.
        refresh_token: The refresh cookie's value, or None when the browser
            sent none.

    Returns:
        The new access token, with ``token_type`` ``"bearer"``.

    Raises:
        AuthenticationError: From the service, if the cookie is missing,
            unknown, expired, or revoked, or its account is deactivated or
            deleted. A cookie that was already exchanged also ends every
            session of its user, the reuse alarm of plan §8.1. The handler
            turns it into a 401 with code ``AUTHENTICATION_FAILED``.
    """
    issued_tokens = service.refresh(db, refresh_token)
    set_refresh_cookie(response, issued_tokens.refresh_token)
    forbid_caching(response)

    return TokenResponse(access_token=issued_tokens.access_token)


@router.post(
    "/logout",
    status_code=204,
    summary="Sign out",
    responses={
        401: {
            "description": (
                "Missing, invalid, or expired access token, or the account is deactivated."
            )
        }
    },
)
def logout(
    user: CurrentUserAllowingPasswordChange,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> None:
    """Sign out on this device. Authenticated.

    This device's session ends: the refresh token in the cookie is revoked,
    or its replacement is, when a refresh of the same cookie has just
    rotated it, so this device can never refresh again. The cookie is
    cleared too, so the browser stops sending it. The user's other devices
    stay signed in. The access token can't be revoked: the web app will
    drop it from memory, and it expires on its own within minutes.

    Signing out always answers 204 with an empty body and clears the
    cookie, even when the cookie is missing, unknown, already revoked, or
    belongs to someone else, so signing out twice is harmless. It needs a
    valid access token, so a caller can only end their own session; with
    an expired one, the web app will refresh first. It stays open while
    ``must_change_password`` is set, so a user can always sign out.

    Args:
        user: The active user the bearer token belongs to.
        response: Holds the headers FastAPI adds to the response; the
            cookie is cleared on it.
        db: Session for this request; the service commits it when a token
            is revoked.
        refresh_token: The refresh cookie's value, or None when the browser
            sent none.

    Raises:
        AuthenticationError: From the dependency, before this runs, if the
            access token is invalid or expired, or the account is
            deactivated. A missing token gets FastAPI's own 401 first. The
            handlers turn both into a 401 with code
            ``AUTHENTICATION_FAILED``.
    """
    service.logout(db, user, refresh_token)
    clear_refresh_cookie(response)


@router.get(
    "/me",
    summary="Get the signed-in user",
    response_model=UserRead,
    responses={
        401: {
            "description": (
                "Missing, invalid, or expired access token, or the account is deactivated."
            )
        }
    },
)
def me(user: CurrentUserAllowingPasswordChange) -> User:
    """Return the signed-in user's account. Authenticated.

    The web app will call this after signing in and after each page reload
    to learn the account's email, name, and role, and whether a password
    change is due; a token response carries none of these. It keeps working
    while ``must_change_password`` is set, so the app can show the
    change-password screen. The route returns the ORM user, and
    ``response_model`` sends only the ``UserRead`` fields, so the password
    hash never leaves the server.

    Args:
        user: The active user the bearer token belongs to.

    Returns:
        The user, sent as ``UserRead``.

    Raises:
        AuthenticationError: From the dependency, before this runs, if the
            access token is invalid or expired, or the account is
            deactivated. A missing token gets FastAPI's own 401 first. The
            handlers turn both into a 401 with code
            ``AUTHENTICATION_FAILED``.
    """
    return user


@router.post(
    "/change-password",
    summary="Change the password",
    response_model=TokenResponse,
    responses={
        400: {
            "description": (
                "Current password is incorrect, or the new password is the same as the current one."
            )
        },
        401: {
            "description": (
                "Missing, invalid, or expired access token, or the account is deactivated."
            )
        },
    },
)
def change_password(
    data: PasswordChange,
    user: CurrentUserAllowingPasswordChange,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Change the signed-in user's password. Authenticated.

    The body is JSON with the current and the new password; the user comes
    from the access token, so a caller can only change their own password.
    On success every session the user had, on every device, is ended, and
    this device gets a new one: a new access token in the body and a new
    refresh token in the ``HttpOnly`` cookie, replacing the old one, in a
    response that tells every cache not to store it. The other devices are
    refused at their next refresh, without a reuse alarm; an access token
    one of them already holds works until it expires, within minutes.

    A refused change answers 400, not 401, because the web app treats a
    401 as an expired session and would sign the user out. It sets no
    cookie: the error handler builds a new response, and nothing changed,
    so the browser keeps its working cookie. An invalid body, such as a new
    password shorter than 15 characters, is a 422 that never contains the
    passwords. The route stays open while ``must_change_password`` is set,
    since it is how a temporary password gets replaced.

    Args:
        data: The current and the new password.
        user: The active user the bearer token belongs to.
        response: Holds the headers FastAPI adds to the response; the new
            refresh cookie and the headers that forbid caching are set on
            it.
        db: Session for this request; the service commits it on success.

    Returns:
        The new access token, with ``token_type`` ``"bearer"``.

    Raises:
        BadRequestError: From the service, if the current password is wrong
            or the new one is the same as the current one. The handler
            turns it into a 400 with code ``BAD_REQUEST``.
        AuthenticationError: From the dependency, before this runs, if the
            access token is invalid or expired, or the account is
            deactivated; and from the service, if the account is
            deactivated or deleted after the request was authenticated. A
            missing token gets FastAPI's own 401 first. The handlers turn
            each into a 401 with code ``AUTHENTICATION_FAILED``.
    """
    issued_tokens = service.change_password(db, user, data)
    set_refresh_cookie(response, issued_tokens.refresh_token)
    forbid_caching(response)

    return TokenResponse(access_token=issued_tokens.access_token)
