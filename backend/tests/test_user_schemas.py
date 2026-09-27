import pytest
from pydantic import ValidationError

from app.core.permissions import Role
from app.modules.users.schemas import UserCreate


def valid_data(**overrides: object) -> dict[str, object]:
    """Return valid ``UserCreate`` input, replacing any given fields.

    Each test changes only the field it is about, so a failure points at
    that field.

    Args:
        **overrides: Field values that replace the defaults.

    Returns:
        A dict to unpack into ``UserCreate``.
    """
    values = {
        "email": "test@example.com",
        "full_name": "test user",
        "password": "Password@1331",
        "role": Role.DOCTOR,
    }

    values.update(overrides)
    return values


@pytest.mark.parametrize("email", ["test@example.com", "Test@Example.com"])
def test_the_email_is_lowercased(email: str) -> None:
    """An email in any letter case is stored in lowercase."""
    data = valid_data(email=email)
    expected_email = "test@example.com"
    user = UserCreate(**data)
    assert user.email == expected_email


def test_a_malformed_email_is_rejected() -> None:
    """An email without a proper domain fails validation on the ``email`` field."""
    data = valid_data(email="test@example")
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**data)

    assert exc_info.value.errors()[0]["loc"] == ("email",)


def test_the_name_is_stripped_of_surrounding_spaces() -> None:
    """Spaces around the full name are removed."""
    data = valid_data(full_name="  Ana  ")
    user = UserCreate(**data)

    assert user.full_name == "Ana"


@pytest.mark.parametrize(
    "full_name",
    [
        pytest.param("a" * 1, id="1 character"),
        pytest.param("a" * 255, id="255 characters"),
    ],
)
def test_a_name_at_the_length_limits_is_accepted(full_name: str) -> None:
    """Names of exactly 1 and 255 characters are accepted unchanged."""
    data = valid_data(full_name=full_name)
    user = UserCreate(**data)

    assert user.full_name == full_name


@pytest.mark.parametrize(
    "full_name", [pytest.param(" ", id="only spaces"), pytest.param("a" * 256, id="too long")]
)
def test_an_invalid_name_is_rejected(full_name: str) -> None:
    """A name of only spaces, or of 256 characters, fails on ``full_name``.

    Spaces are stripped before the length check, so a blank name becomes
    empty and is rejected.
    """
    data = valid_data(full_name=full_name)
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**data)

    assert exc_info.value.errors()[0]["loc"] == ("full_name",)


def test_the_password_is_kept_exactly_as_typed() -> None:
    """Spaces around the password are kept.

    They are part of the password; stripping them would lock the user out.
    """
    data = valid_data(password=" padded pass ")
    user = UserCreate(**data)

    assert user.password.get_secret_value() == " padded pass "


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("x" * 12, id="12 characters"),
        pytest.param("x" * 128, id="128 characters"),
    ],
)
def test_a_password_at_the_length_limits_is_accepted(password: str) -> None:
    """Passwords of exactly 12 and 128 characters are accepted unchanged."""
    data = valid_data(password=password)
    user = UserCreate(**data)

    assert user.password.get_secret_value() == password


def test_the_password_is_hidden_when_printed() -> None:
    """Printing the whole model never shows the password.

    The model is what ends up in logs and tracebacks, so this checks
    ``repr`` and ``str`` of the model, not just of the password field.
    """
    data = valid_data(password="Password@1331")
    user = UserCreate(**data)

    assert "Password@1331" not in repr(user)
    assert "Password@1331" not in str(user)


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("x" * 11, id="11 characters"),
        pytest.param("x" * 129, id="129 characters"),
    ],
)
def test_an_invalid_password_is_rejected(password: str) -> None:
    """Passwords of 11 and 129 characters fail on the ``password`` field."""
    data = valid_data(password=password)
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**data)

    assert exc_info.value.errors()[0]["loc"] == ("password",)


def test_an_unknown_role_is_rejected() -> None:
    """A role that isn't a ``Role`` value fails on the ``role`` field."""
    data = valid_data(role="superuser")
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**data)

    assert exc_info.value.errors()[0]["loc"] == ("role",)
