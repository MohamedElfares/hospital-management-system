"""Dependencies that routes declare to identify the caller.

A route that needs the signed-in user asks for ``CurrentUser``, and FastAPI
runs the chain before the route body: read the bearer token from the
``Authorization`` header, open the request's database session, and ask the
auth service which active user the token belongs to. This module only
connects HTTP to the service; every rule about who counts as signed in
lives in ``app.modules.auth.service``, where it can be tested without HTTP.
Permission checks will join it here as ``require_permission``.
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

# Auth rules; turns an access token into the active user it belongs to.
from app.modules.auth import service

# The users table's ORM model; the type of the signed-in user.
from app.modules.users.models import User

# Without the header, or with another scheme such as Basic, this answers 401
# with WWW-Authenticate: Bearer before the route runs. tokenUrl only tells
# Swagger UI's Authorize button where the sign-in form posts.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Return the signed-in user for this request.

    The token only says who the caller was when it was issued, so the auth
    service loads the account from the database to confirm it still exists
    and is active. FastAPI runs each dependency once per request, so the
    session used here is the same one the route receives: the user belongs
    to that session and can be used in the route's own queries.

    A pending password change doesn't stop this dependency, because the
    current-user endpoint must keep working while one is due; routes that
    must be blocked in that state get a separate gate.

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


# Shorthand a route uses to receive the signed-in user, as ``user: CurrentUser``.
CurrentUser = Annotated[User, Depends(get_current_user)]
