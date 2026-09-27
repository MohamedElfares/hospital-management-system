"""Password hashing and verification.

Passwords are never stored. Each one is hashed with Argon2id through pwdlib:
a slow, memory-hard function with a random salt per password, so a leaked
``users`` table can't be turned back into passwords and each hash has to be
attacked separately. The rest of the backend calls ``hash_password`` and
``verify_password`` and never imports pwdlib, so the algorithm or its
settings can change in this one file.
"""

# Standard-library logging; records unsupported hashes without their contents.
import logging

# Cryptographically secure random values; the unguessable input of _DUMMY_HASH.
import secrets

# pwdlib's hasher; recommended() gives Argon2id with safe default settings.
from pwdlib import PasswordHash

# Raised by pwdlib when a stored hash isn't in a format it recognizes.
from pwdlib.exceptions import UnknownHashError

logger = logging.getLogger(__name__)

# One hasher for the whole process, so every hash uses the same settings.
_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a password for storage in ``users.password_hash``.

    The result is a self-describing Argon2id string such as
    ``$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>``: it carries the
    algorithm, the settings, and a new random salt, so hashing the same
    password twice gives two different strings that both verify. Hashing
    takes tens of milliseconds on purpose, which makes guessing slow for an
    attacker who has stolen the hashes. The password is used as given:
    rules such as a minimum length belong in the request schema.

    Args:
        password: The plain password. Never logged or stored.

    Returns:
        The encoded hash, about 97 characters long.
    """
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a submitted password against a stored hash.

    pwdlib reads the algorithm, settings, and salt from ``password_hash``,
    hashes ``password`` the same way, and compares the results in constant
    time, so the comparison doesn't reveal how much of the hash matched.
    Passwords are compared exactly: case and surrounding spaces matter.

    A stored hash that pwdlib doesn't recognize, such as a bcrypt value or
    corrupted data, counts as a failed match instead of an error. Sign-in
    then fails with the usual 401 rather than a 500, and a warning is
    logged so the bad row gets noticed. The warning never contains the
    hash or the password.

    Args:
        password: The password the user submitted.
        password_hash: The stored hash from ``users.password_hash``.

    Returns:
        True if the password matches the hash, and False if it doesn't or
        the hash is in an unsupported format.
    """
    try:
        return _password_hash.verify(password, password_hash)
    except UnknownHashError:
        logger.warning("Password hash uses an unknown or unsupported format")
        return False


# Sign-in verifies against this hash when the email matches no user, so an
# unknown email takes as long to reject as a wrong password and response
# times can't reveal which emails have accounts. It is built with
# hash_password, not pasted in, so it always has the same settings, and
# therefore the same cost, as real hashes.
_DUMMY_HASH = hash_password(secrets.token_urlsafe())
