"""Request and response schemas for the auth endpoints.

``LoginForm`` is the sign-in form: FastAPI's OAuth2 password form with
length limits. ``TokenResponse`` is the body of every route that issues
tokens: sign-in, refresh, and the password change. ``PasswordChange`` is
the password change's JSON body. ``GET /auth/me`` returns the users
module's ``UserRead``, so it needs no schema here. These classes also
decide how OpenAPI documents the requests and responses.

Only the access token ever appears in a response body: the refresh token
travels in its ``HttpOnly`` cookie alone, so no schema here has a field
for it, and a response model can't leak it by accident. Both passwords of
a password change arrive as ``SecretStr``, so the model never shows them
when printed or logged. The sign-in form's password is a plain ``str``,
as FastAPI's form class declares it, but the form is a plain class whose
printed form shows no field values.
"""

# Attaches a form field's declaration to its type in the sign-in form.
from typing import Annotated

# Restricts token_type to the one value the OAuth2 bearer scheme expects.
from typing import Literal

# Declares a field of a form body and its limits; the sign-in form's fields.
from fastapi import Form

# FastAPI's form for the OAuth2 password flow; LoginForm keeps its fields and adds limits.
from fastapi.security import OAuth2PasswordRequestForm

# Base class for Pydantic models; documents the body in OpenAPI.
from pydantic import BaseModel

# Declares field constraints; caps the length of the current password.
from pydantic import Field

# String that hides its value when printed; the type of the current password.
from pydantic import SecretStr

# The users.email column's size; the longest email the sign-in form accepts.
from app.modules.users.schemas import EMAIL_MAX_LENGTH

# Longest password the rule allows; the maximum of the sign-in and current passwords.
from app.modules.users.schemas import PASSWORD_MAX_LENGTH

# The shared password rule, the same one used when a user is created.
from app.modules.users.schemas import Password


class LoginForm(OAuth2PasswordRequestForm):
    """The sign-in form: FastAPI's OAuth2 password form, with length limits.

    Sign-in reads the form of the OAuth2 password flow, with the email in
    ``username``, so Swagger UI's Authorize button works (plan §8.1). This
    subclass declares the same six fields as FastAPI's form, so requests
    and the OpenAPI schema keep their shape, and caps the two fields the
    API reads, as plan §12 asks of every input. A longer value can't
    belong to an account: no stored email is longer than the
    ``users.email`` column's ``EMAIL_MAX_LENGTH``, and no password can be
    set longer than ``PASSWORD_MAX_LENGTH``. FastAPI refuses it with a 422
    before any query or password check, and the 422 says nothing about
    which accounts exist.

    The other four fields belong to the OAuth2 form, and Swagger UI sends
    some of them, but the API never reads them, so they keep FastAPI's
    declarations; Starlette refuses any form field longer than 1 MiB.

    Attributes:
        grant_type: ``"password"`` or None; any other value is a 422.
        username: The email as typed, at most ``EMAIL_MAX_LENGTH``
            characters.
        password: The password as typed, at most ``PASSWORD_MAX_LENGTH``
            characters. Never logged or stored.
        scopes: The requested scopes, split on spaces; unused.
        client_id: An OAuth2 client ID, or None; unused.
        client_secret: An OAuth2 client secret, or None; unused.
    """

    def __init__(
        self,
        *,
        grant_type: Annotated[str | None, Form(pattern="^password$")] = None,
        username: Annotated[str, Form(max_length=EMAIL_MAX_LENGTH)],
        password: Annotated[
            str,
            Form(max_length=PASSWORD_MAX_LENGTH, json_schema_extra={"format": "password"}),
        ],
        scope: Annotated[str, Form()] = "",
        client_id: Annotated[str | None, Form()] = None,
        client_secret: Annotated[
            str | None,
            Form(json_schema_extra={"format": "password"}),
        ] = None,
    ) -> None:
        """Read the form's fields, refusing an email or password over its limit.

        FastAPI builds the form from these parameters, so their
        declarations are what it validates and documents. They match
        FastAPI's own form, apart from the two maximums, and the parent
        stores the values.

        Args:
            grant_type: The OAuth2 grant type, ``"password"`` when sent.
            username: The email typed at sign-in.
            password: The password typed at sign-in.
            scope: Space-separated OAuth2 scopes, empty when none.
            client_id: The OAuth2 client ID, if sent.
            client_secret: The OAuth2 client secret, if sent.
        """
        super().__init__(
            grant_type=grant_type,
            username=username,
            password=password,
            scope=scope,
            client_id=client_id,
            client_secret=client_secret,
        )


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

    The new password follows the shared ``Password`` rule, 15 to 128
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
        new_password: The password to replace it, 15 to 128 characters.
    """

    current_password: SecretStr = Field(max_length=PASSWORD_MAX_LENGTH)
    new_password: Password
