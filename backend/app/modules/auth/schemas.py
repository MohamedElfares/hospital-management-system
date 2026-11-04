"""Request and response schemas for the auth endpoints.

``TokenResponse`` is the body of every route that issues tokens: sign-in,
refresh, and the password change. ``PasswordChange`` is the password
change's JSON body. Sign-in reads FastAPI's ``OAuth2PasswordRequestForm``
instead, and ``GET /auth/me`` returns the users module's ``UserRead``, so
neither needs a schema here. The models also decide how OpenAPI documents
these bodies.

Only the access token ever appears in a response body: the refresh token
travels in its ``HttpOnly`` cookie alone, so no schema here has a field
for it, and a response model can't leak it by accident. Both passwords of
a password change arrive as ``SecretStr``, so the model never shows them
when printed or logged. The sign-in form's password is a plain ``str``,
as FastAPI's form class declares it.
"""

# Restricts token_type to the one value the OAuth2 bearer scheme expects.
from typing import Literal

# Base class for Pydantic models; documents the body in OpenAPI.
from pydantic import BaseModel

# Declares field constraints; caps the length of the current password.
from pydantic import Field

# String that hides its value when printed; the type of the current password.
from pydantic import SecretStr

# Longest password the rule allows; also the current password's maximum.
from app.modules.users.schemas import PASSWORD_MAX_LENGTH

# The shared password rule, the same one used when a user is created.
from app.modules.users.schemas import Password


class TokenResponse(BaseModel):
    """Body of a successful sign-in, refresh, or password change.

    The shape follows the OAuth2 token response (RFC 6749 §5.1), whose
    required fields are ``access_token`` and ``token_type``, so Swagger
    UI's Authorize button and standard OAuth2 clients understand it
    without custom code. ``expires_in``, which the RFC recommends, is left
    out: the web app will refresh after a page reload and when a request
    gets a 401 (plan §8.1), so it doesn't need the lifetime. It will keep
    the access token in memory only and send it as
    ``Authorization: Bearer <token>``.

    Attributes:
        access_token: The signed, short-lived JWT that names the user.
        token_type: Always ``"bearer"``, the token type the API accepts in
            the ``Authorization`` header (RFC 6750). The ``Literal`` type
            means no other value can be returned, and OpenAPI shows it as
            a constant.
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"


class PasswordChange(BaseModel):
    """Validated input for changing the signed-in user's own password.

    The new password follows the shared ``Password`` rule, 12 to 128
    characters, like every other way a password is set. The current
    password has only a maximum. It is checked against the stored hash,
    not against the rule, so a minimum would add nothing: an empty one
    passes here and fails the service's check. No password can be set
    longer than 128 characters, so a longer current password can never be
    right; refusing it with a 422 spares the service an Argon2 check and
    bounds the field, as plan §12 asks of every input. The maximum isn't
    about hashing time, which barely grows with length under Argon2.

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
