"""Schemas for user accounts: the email and password rules, account input, and output.

An input schema checks and cleans data before any business rule runs.
``UserCreate`` serves every way a staff account is created, the
``create-admin`` command now and the staff administration API later
(IAM-5), so the email and name rules are written once; patient accounts
come from portal activation instead (plan §8.5). The email rule is the
``Email`` type, which the users service also applies to the email typed at
sign-in, so a lookup always meets the stored form. The password rule is the
``Password`` type, shared with every schema that sets a password, such as
the auth module's ``PasswordChange``. Built directly, as ``create-admin``
builds it, a schema raises Pydantic's ``ValidationError`` for invalid
input; as a request body, FastAPI reports the same errors as a
``RequestValidationError``, which the API turns into a 422 response.

The output schema decides which fields of a user ever leave the API, so the
password hash and internal flags can't be sent by accident.
"""

# Unicode character categories; finds control characters in the full name.
import unicodedata

# The UUID type of user IDs; the type of UserRead.id.
import uuid

# Attaches rules to a type; builds the Email and Password types and the name field.
from typing import Annotated

# Runs a function on a value after Pydantic's own checks; lowercases emails, checks names.
from pydantic import AfterValidator

# Base class for Pydantic models that validate their fields on creation.
from pydantic import BaseModel

# Model settings; lets UserRead read its fields from an ORM object's attributes.
from pydantic import ConfigDict

# Email address that email-validator checks and normalizes; the base of the Email type.
from pydantic import EmailStr

# Declares field constraints; sets the password length limits.
from pydantic import Field

# String that hides its value when printed; keeps the password out of logs.
from pydantic import SecretStr

# Length and whitespace rules for a string field; used for the full name.
from pydantic import StringConstraints

# The role enum; the type of the role field in both schemas.
from app.core.permissions import Role

# The one email rule: email-validator's checks and normal form, then
# lowercase. UserCreate stores an email in this form, and the users service
# puts the email typed at sign-in through the same rule, so the two can
# never disagree about how an address is written.
Email = Annotated[EmailStr, AfterValidator(str.lower)]

# The users.email column's size, so no account's email is longer. Sign-in
# refuses a longer username before any lookup, as plan §12 asks of every
# input; public, so the auth schemas and the tests use the same number.
EMAIL_MAX_LENGTH = 255

# Plan §8.1: 15 to 128 characters and no composition rules. NIST SP 800-63B-4
# requires at least 15 characters for a password that is the only factor of a
# sign-in, as every password here is. Pydantic counts characters, not bytes.
# The maximum bounds the input, as plan §12 asks of every field; it isn't
# about hashing time, which barely grows with length under Argon2. Public, so
# the auth schemas, the CLI's message, and the tests use the same numbers.
PASSWORD_MIN_LENGTH = 15
PASSWORD_MAX_LENGTH = 128

# The one password rule for every way a password is set (plan §8.1); today
# UserCreate and the auth module's PasswordChange use it. A SecretStr shows
# "**********" when printed, so a model holding it can't leak it into a log.
Password = Annotated[
    SecretStr,
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
]


def _reject_control_characters(text: str) -> str:
    """Refuse text that holds a control character.

    A full name is one line of display text, so no control character
    belongs in it. PostgreSQL can't store NUL at all, so without this check
    a name holding one would fail the insert with a database error, and
    tabs, line breaks, or terminal escape codes would break the screens
    that show the name. Only Unicode's control category, ``Cc``, is
    refused: U+0000 to U+001F and U+007F to U+009F. Invisible formatting
    characters stay allowed, because some scripts need them inside names,
    such as the zero-width non-joiner in Persian.

    Args:
        text: The value after Pydantic has stripped surrounding whitespace,
            so a trailing line break is already gone.

    Returns:
        The value, unchanged.

    Raises:
        ValueError: If the value holds a control character. Pydantic
            reports it as a validation error on the field.
    """
    if any(unicodedata.category(character) == "Cc" for character in text):
        raise ValueError("must not contain control characters, such as tabs or line breaks")

    return text


class UserCreate(BaseModel):
    """Validated input for creating one user account.

    The email follows the shared ``Email`` rule. ``EmailStr`` checks the
    address with email-validator and returns its normalized form:
    surrounding spaces dropped, Unicode in NFC form, and the domain mapped
    to its standard form, so full-width letters there become ASCII. The
    address is then lowercased, which satisfies the database's lowercase
    CHECK. Sign-in applies the same rule to the email it is given, so the
    account is found however its address was typed. The full name is
    stripped of surrounding spaces, and a name of only spaces, or one that
    holds a control character such as NUL, is rejected before it reaches
    the database. The password is kept exactly as typed, spaces included,
    because changing it would lock the user out; hashing only puts it in
    Unicode NFC, which every password check does as well. That is why the
    model has no ``str_strip_whitespace`` setting: it would strip the
    ``SecretStr`` password too.

    The password follows the shared ``Password`` rule of 15 to 128
    characters with no composition rules (NIST SP 800-63B-4), the same rule
    every other way of setting a password uses. It is a ``SecretStr``, so
    printing or logging the model shows ``**********``; the real value is
    read only once, with ``get_secret_value()``, to hash it. Pydantic's
    validation errors still contain the rejected input, so callers must
    report only each error's location and message, never the error itself.

    Attributes:
        email: Sign-in email, validated, normalized, and lowercased.
        full_name: Display name, 1 to 255 characters after stripping, with
            no control characters.
        password: Plain password to hash, 15 to 128 characters.
        role: The new user's role.
    """

    email: Email
    full_name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=255,
        ),
        AfterValidator(_reject_control_characters),
    ]
    password: Password
    role: Role


class UserRead(BaseModel):
    """A user account as the API shows it.

    Used as a route's ``response_model``: FastAPI copies only these fields
    into the response, so a route can return the ORM ``User`` and the
    password hash still never leaves the server. ``from_attributes`` lets
    Pydantic read the values from the object's attributes instead of a
    dict. Only ``GET /auth/me`` returns it so far. ``is_active`` and
    ``is_demo`` are left out: a caller who reaches that endpoint is always
    active, and nothing reads the demo flag yet.

    Attributes:
        id: The account's ID.
        email: Sign-in email, stored lowercase.
        full_name: Display name.
        role: The account's role; the web app will choose which screens to
            show from it (WEB-2).
        must_change_password: True while a temporary password must be
            replaced; the web app will then show the change-password
            screen.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    must_change_password: bool
