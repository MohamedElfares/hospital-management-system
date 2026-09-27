import pytest

from app.core.security import _DUMMY_HASH
from app.core.security import hash_password
from app.core.security import verify_password

PASSWORD: str = "Password@1331"
OLD_BCRYPT_HASH = "$2a$12$xmwWaOMD74tVfixmTpxpWe7oZiybi9crvSu0lbrbe9NXCx8CS1nq"


def test_a_hash_is_argon2_and_not_the_password() -> None:
    """Hashing gives an Argon2id string that doesn't contain the password as is."""
    hashed_password: str = hash_password(PASSWORD)

    assert hashed_password.startswith("$argon2id$")
    assert hashed_password != PASSWORD


def test_the_same_password_gets_a_different_hash_each_time() -> None:
    """Two hashes of one password differ, and both still verify.

    Each hash gets its own random salt, so users who share a password don't
    share a hash, and one cracked hash doesn't unlock the others.
    """
    first_hashed_password: str = hash_password(PASSWORD)
    second_hashed_password: str = hash_password(PASSWORD)

    assert first_hashed_password != second_hashed_password
    assert verify_password(PASSWORD, first_hashed_password) is True
    assert verify_password(PASSWORD, second_hashed_password) is True


def test_the_right_password_verifies() -> None:
    """The password that was hashed verifies against its own hash."""
    hashed_password: str = hash_password(PASSWORD)

    assert verify_password(PASSWORD, hashed_password) is True


@pytest.mark.parametrize(
    ("submitted", "stored"),
    [
        pytest.param("password@1331", "Password123", id="totally wrong"),
        pytest.param("S3cret", "s3cret", id="different case"),
        pytest.param("s3cret ", "s3cret", id="trailing space"),
    ],
)
def test_a_wrong_password_is_rejected(submitted: str, stored: str) -> None:
    """A submitted password that differs from the stored one fails to verify.

    Passwords are compared exactly, so even a small difference must be
    rejected rather than normalized away.
    """
    hashed_password: str = hash_password(stored)

    assert verify_password(submitted, hashed_password) is False


def test_a_unicode_password_round_trips() -> None:
    """A password with non-ASCII characters hashes and then verifies."""
    unicode_password = "Pässwörd123!"
    hashed_password = hash_password(unicode_password)

    assert verify_password(unicode_password, hashed_password) is True


def test_a_very_long_password_round_trips() -> None:
    """A 3,000-character password hashes and then verifies.

    Argon2 has no input limit, unlike bcrypt, which silently ignores
    everything after 72 bytes.
    """
    long_password = "abc" * 1000
    hashed_password = hash_password(long_password)

    assert verify_password(long_password, hashed_password) is True


@pytest.mark.parametrize(
    "hashed_password",
    [
        pytest.param(OLD_BCRYPT_HASH, id="bcrypt-hash"),
        pytest.param("not-a-real-hash", id="garbage"),
    ],
)
def test_an_unsupported_hash_fails_and_logs_a_safe_warning(
    hashed_password: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bcrypt or corrupted stored hash fails to verify, with a safe warning.

    pwdlib raises for hashes it doesn't recognize; ``verify_password``
    turns that into False so sign-in answers 401, not 500. The warning must
    be logged, and it must not contain the hash.
    """
    with caplog.at_level("WARNING"):
        result = verify_password("some-password", hashed_password)

    assert result is False
    assert any(record.levelname == "WARNING" for record in caplog.records)
    assert hashed_password not in caplog.text


def test_the_dummy_hash_is_argon2_and_matches_no_password() -> None:
    """The dummy hash is a real Argon2id hash that an ordinary password doesn't match.

    Being Argon2id with the normal settings is what makes verifying against
    it take as long as a real sign-in.
    """
    assert verify_password(PASSWORD, _DUMMY_HASH) is False
    assert _DUMMY_HASH.startswith("$argon2id$")
