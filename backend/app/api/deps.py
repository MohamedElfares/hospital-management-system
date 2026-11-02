"""Dependencies that routes declare to identify the caller.

A route that needs the signed-in user asks for ``CurrentUser``, and FastAPI
runs the chain before the route body: read the bearer token from the
``Authorization`` header, open the request's database session, ask the auth
service which active user the token belongs to, and refuse that user while
a password change is pending. This module only connects HTTP to the
service; every rule about who counts as signed in lives in
``app.modules.auth.service``, where it can be tested without HTTP.

The password-change gate is on by default: ``CurrentUser`` applies it, so a
new route can't forget it. The few routes the change itself needs opt out
by asking for ``CurrentUserAllowingPasswordChange`` instead, which makes
the exemption visible in the route's signature. Permission checks will join
this module as ``require_permission``, built on ``get_current_user`` so
they keep the gate.
"""

# Attaches a dependency to a parameter's type.
from typing import Annotated

# Asks FastAPI to run a dependency and pass its result to the route.
from fastapi import Depends

# Reads the bearer token from the Authorization header and documents it in OpenAPI.
from fastapi.security import OAuth2PasswordBearer

# Type of the database session the service reads the user with.
from sqlalchemy.orm import Session

# Provides one database session for the request.
from app.db.session import get_db

# Auth rules; finds the user a token belongs to and applies the password-change gate.
from app.modules.auth import service

# The users table's ORM model; the type of the signed-in user.
from app.modules.users.models import User

# Without the header, or with another scheme such as Basic, this answers 401
# with WWW-Authenticate: Bearer before the route runs. tokenUrl only tells
# Swagger UI's Authorize button where the sign-in form posts.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user_allowing_password_change(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Return the signed-in user, even while a password change is pending.

    The token only says who the caller was when it was issued, so the auth
    service loads the account from the database to confirm it still exists
    and is active. FastAPI runs each dependency once per request, so the
    session used here is the same one the route receives: the user belongs
    to that session and can be used in the route's own queries.

    This is the base of the chain and skips the password-change gate. Only
    the routes a user with a temporary password still needs use it
    directly: reading their own account, signing out, and changing the
    password. Every other route gets the gate through ``get_current_user``.

    Args:
        token: The bearer token from the ``Authorization`` header. It can be
            empty when the header is just ``Bearer``.
        db: The request's database session.

    Returns:
        The active user the token belongs to.

    Raises:
        AuthenticationError: From the service, if the token is invalid or
            expired or its user is missing or deactivated. The handler turns
            it into a 401 with code ``AUTHENTICATION_FAILED``.
    """
    return service.get_authenticated_user(db, token)


def get_current_user(
    user: Annotated[User, Depends(get_current_user_allowing_password_change)],
) -> User:
    """Return the signed-in user, refusing one who must change their password.

    It builds on ``get_current_user_allowing_password_change``, so the token
    and the account are checked first: a bad token or a deactivated account
    gets a 401, and only a valid, active user can get the 403 from the
    gate. FastAPI runs that dependency once per request, so the user is
    loaded only once.

    Args:
        user: The active user the bearer token belongs to.

    Returns:
        The same user, who has no password change pending.

    Raises:
        PermissionDeniedError: From the service, if ``must_change_password``
            is set. The handler turns it into a 403 with code
            ``PASSWORD_CHANGE_REQUIRED``.
    """
    service.ensure_password_change_not_pending(user)

    return user


# Shorthand a route uses to receive the signed-in user, as ``user: CurrentUser``.
# Blocked while a password change is pending; the default for every route.
CurrentUser = Annotated[User, Depends(get_current_user)]

# The same user without the password-change gate, only for the routes the
# change itself needs: /auth/me, /auth/logout, and /auth/change-password.
CurrentUserAllowingPasswordChange = Annotated[
    User,
    Depends(get_current_user_allowing_password_change),
]
