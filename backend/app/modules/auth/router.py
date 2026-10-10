"""HTTP routes for signing in.

The router handles HTTP only: it reads the form, calls one service function,
and turns the result into a response body and a cookie. Every rule about
who may sign in lives in the service, and failures come back as domain
errors that the exception handlers turn into the standard error body.

All routes here are Public: signing in is how a caller becomes
authenticated, so no token can be required yet.
"""

# Attaches a dependency to a parameter's type.
from typing import Annotated

# Groups these routes under /auth so the API router can include them as one unit.
from fastapi import APIRouter

# Asks FastAPI to build the form and the database session for the route.
from fastapi import Depends

# The response FastAPI sends; the route sets the refresh cookie on it.
from fastapi import Response

# Reads the OAuth2 password form: the email in "username" and the password.
from fastapi.security import OAuth2PasswordRequestForm

# Type of the database session passed to the service.
from sqlalchemy.orm import Session

# Writes the refresh token into its HttpOnly cookie with every security flag.
from app.core.security import set_refresh_cookie

# Provides one database session for the request.
from app.db.session import get_db

# Sign-in rules; imported as a module so tests can replace one function.
from app.modules.auth import service

# Body of a successful sign-in: the access token and its type.
from app.modules.auth.schemas import TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    summary="Sign in",
    response_model=TokenResponse,
    responses={401: {"description": "Incorrect email or password."}},
)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Sign in with an email and password. Public.

    The request is a form (``application/x-www-form-urlencoded``) with the
    email in the ``username`` field, as the OAuth2 password flow requires,
    so Swagger UI's Authorize button works. A JSON body is rejected with a
    422. On success, the access token goes in the body and the refresh token
    goes only into the ``HttpOnly`` cookie, so page scripts can never read
    it. Every failed sign-in, whether the email is unknown, the password is
    wrong, or the account is deactivated, gets the same 401 and no cookie.

    Args:
        form: The OAuth2 password form; ``username`` holds the email.
        response: The response being built; the refresh cookie is set on it.
        db: Session for this request; the service commits it on success.

    Returns:
        The access token, with ``token_type`` ``"bearer"``.

    Raises:
        AuthenticationError: From the service, for any failed sign-in. The
            handler turns it into a 401 with code ``AUTHENTICATION_FAILED``.
    """
    result = service.login(db, form.username, form.password)
    set_refresh_cookie(response, result.refresh_token)

    return TokenResponse(access_token=result.access_token)
