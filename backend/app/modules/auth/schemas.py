"""Response schemas for the auth endpoints.

These models define what the auth routes send back and how OpenAPI
documents it. Only the access token ever appears in a response body: the
refresh token travels in its ``HttpOnly`` cookie alone, so no schema here
has a field for it, and a response model can't leak it by accident.
"""

# Restricts token_type to the one value the OAuth2 bearer scheme expects.
from typing import Literal

# Base class for Pydantic models; documents the body in OpenAPI.
from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Body of a successful sign-in.

    The shape follows the OAuth2 password flow (RFC 6749 §5.1), so
    Swagger UI's Authorize button and standard OAuth2 clients understand it
    without custom code. The web client keeps the access token in memory
    only and sends it as ``Authorization: Bearer <token>``; when it expires,
    the client gets a new one through the refresh cookie.

    Attributes:
        access_token: The signed, short-lived JWT that names the user.
        token_type: Always ``"bearer"``, as the OAuth2 spec requires; the
            ``Literal`` type means no other value can be returned.
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"
