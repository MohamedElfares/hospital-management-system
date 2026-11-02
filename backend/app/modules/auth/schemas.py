"""Request and response schemas for the auth endpoints.

These models define what the auth routes accept and send back, and how
OpenAPI documents it. Only the access token ever appears in a response
body: the refresh token travels in its ``HttpOnly`` cookie alone, so no
schema here has a field for it, and a response model can't leak it by
accident. Passwords arrive as ``SecretStr``, so a model holding one never
shows it when printed or logged.
"""

# Restricts token_type to the one value the OAuth2 bearer scheme expects.
from typing import Literal

# Base class for Pydantic models; documents the body in OpenAPI.
from pydantic import BaseModel

# Declares field constraints; caps the length of the current password.
from pydantic import Field

# String that hides its value when printed; keeps both passwords out of logs.
from pydantic import SecretStr

# Longest password the rule allows; no stored password can be longer.
from app.modules.users.schemas import PASSWORD_MAX_LENGTH

# The shared password rule, the same one used when a user is created.
from app.modules.users.schemas import Password


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


class PasswordChange(BaseModel):
    """Validated input for changing the signed-in user's own password.

    The new password follows the shared ``Password`` rule, 12 to 128
    characters, like every other way a password is set. The current
    password only has a maximum: it is checked against the stored hash, not
    against the rule, so a minimum would add nothing, while the maximum
    caps the hashing work, since no stored password can be longer.

    Whether the current password is right, and whether the new one differs
    from it, depends on the stored hash, so the service checks both. Both
    values are kept exactly as typed, spaces included, and read only once,
    with ``get_secret_value()``.

    Attributes:
        current_password: The password the user signs in with now, at most
            128 characters.
        new_password: The password to replace it, 12 to 128 characters.
    """

    current_password: SecretStr = Field(max_length=PASSWORD_MAX_LENGTH)
    new_password: Password
