"""Schemas for user accounts: the password rule, input for creating users, and output.

An input schema checks and cleans data before any business rule runs. The
same schema serves every way a user is created, the ``create-admin`` command
now and the staff administration API later (IAM-5), so the email and name
rules are written once. The password rule is the ``Password`` type, shared
with every schema that sets a password, such as changing one. Invalid input
raises Pydantic's ``ValidationError``, which the API turns into a 422
response.

The output schema decides which fields of a user ever leave the API, so the
password hash and internal flags can't be sent by accident.
"""

# The UUID type of user ids; the type of UserRead.id.
import uuid

# Attaches validation rules and extra processing to a type annotation.
from typing import Annotated

# Runs a function on a value after Pydantic's own checks; lowercases emails.
from pydantic import AfterValidator

# Base class for Pydantic models that validate their fields on creation.
from pydantic import BaseModel

# Model settings; lets UserRead read its fields from an ORM object's attributes.
from pydantic import ConfigDict

# String type that must be a valid email address; checked by email-validator.
from pydantic import EmailStr

# Declares field constraints; sets the password length limits.
from pydantic import Field

# String that hides its value when printed; keeps the password out of logs.
from pydantic import SecretStr

# Length and whitespace rules for a string field; used for the full name.
from pydantic import StringConstraints

# The role enum a new user must be given.
from app.core.permissions import Role

# Plan §8.1: 12 to 128 characters and no composition rules (NIST SP 800-63B).
# The maximum also caps the work of hashing, since Argon2 reads every byte.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# The one password rule for every way a password is set: creating a user,
# changing a password, and later resetting one. A SecretStr shows
# "**********" when printed, so a model holding it can't leak it into a log.
Password = Annotated[
    SecretStr,
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
]


class UserCreate(BaseModel):
    """Validated input for creating one user account.

    The email is lowercased here, so lookups and the database's lowercase
    CHECK agree. The full name is stripped of surrounding spaces, and a name
    of only spaces is rejected. The password is kept exactly as typed,
    spaces included, because changing it would lock the user out: the model
    config deliberately doesn't strip every string, since that would also
    strip the password.

    The password follows the shared ``Password`` rule of 12 to 128
    characters with no composition rules (NIST SP 800-63B), the same rule
    every other way of setting a password uses. It is a ``SecretStr``, so
    printing or logging the model shows ``**********``; the real value is
    read only once, with ``get_secret_value()``, to hash it. Pydantic's
    validation errors still contain the rejected input, so callers must
    report only each error's location and message, never the error itself.

    Attributes:
        email: Sign-in email, validated and lowercased.
        full_name: Display name, 1 to 255 characters after stripping.
        password: Plain password to hash, 12 to 128 characters.
        role: The new user's role.
    """

    email: Annotated[EmailStr, AfterValidator(str.lower)]
    full_name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=255,
        ),
    ]
    password: Password
    role: Role


class UserRead(BaseModel):
    """A user account as the API shows it.

    Used as a route's ``response_model``: FastAPI copies only these fields
    into the response, so a route can return the ORM ``User`` and the
    password hash still never leaves the server. ``from_attributes`` lets
    Pydantic read the values from the object's attributes instead of a
    dict. ``is_active`` and ``is_demo`` are left out: a caller who can reach
    the current-user endpoint is always active, and nothing needs the demo
    flag yet. The staff administration endpoints will reuse this schema.

    Attributes:
        id: The account's id.
        email: Sign-in email, stored lowercase.
        full_name: Display name.
        role: The account's role; the web app chooses its menus from it.
        must_change_password: True while a temporary password must be
            replaced; the web app shows the change-password screen.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    must_change_password: bool
