import pytest
from pydantic import ValidationError

from app.core.permissions import Role
from app.modules.users.schemas import UserCreate


def _valid_values(**overrides: object) -> dict[str, object]:
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
        "password": "Correct-Password-1",
        "role": Role.DOCTOR,
    }

    values.update(overrides)
    return values


@pytest.mark.parametrize("email", ["test@example.com", "Test@Example.com"])
def test_the_email_is_lowercased(email: str) -> None:
    """An email in any letter case is stored in lowercase."""
    values = _valid_values(email=email)
    expected_email = "test@example.com"
    data = UserCreate(**values)
    assert data.email == expected_email


def test_a_malformed_email_is_rejected() -> None:
    """An email without a proper domain fails validation on the ``email`` field."""
    values = _valid_values(email="test@example")
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    assert exc_info.value.errors()[0]["loc"] == ("email",)


def test_the_name_is_stripped_of_surrounding_spaces() -> None:
    """Spaces around the full name are removed."""
    values = _valid_values(full_name="  Ana  ")
    data = UserCreate(**values)

    assert data.full_name == "Ana"


@pytest.mark.parametrize(
    "full_name",
    [
        pytest.param("a" * 1, id="1 character"),
        pytest.param("a" * 255, id="255 characters"),
    ],
)
def test_a_name_at_the_length_limits_is_accepted(full_name: str) -> None:
    """Names of exactly 1 and 255 characters are accepted unchanged."""
    values = _valid_values(full_name=full_name)
    data = UserCreate(**values)

    assert data.full_name == full_name


@pytest.mark.parametrize(
    "full_name", [pytest.param(" ", id="only spaces"), pytest.param("a" * 256, id="too long")]
)
def test_an_invalid_name_is_rejected(full_name: str) -> None:
    """A name of only spaces, or of 256 characters, fails on ``full_name``.

    Spaces are stripped before the length check, so a blank name becomes
    empty and is rejected.
    """
    values = _valid_values(full_name=full_name)
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    assert exc_info.value.errors()[0]["loc"] == ("full_name",)


@pytest.mark.parametrize(
    "full_name",
    [
        pytest.param("Ana\x00Smith", id="nul"),
        pytest.param("Ana\tSmith", id="tab"),
        pytest.param("Ana\nSmith", id="line-break"),
        pytest.param("Ana\x1b[31mSmith", id="escape-code"),
        pytest.param("Ana\x7fSmith", id="delete"),
        pytest.param("Ana\x85Smith", id="next-line"),
    ],
)
def test_a_name_with_a_control_character_is_rejected(full_name: str) -> None:
    """A control character inside the name fails on ``full_name``.

    NUL is the case that matters most, because PostgreSQL can't store it;
    the others are common C0 controls, DEL, and a C1 control. Each sits
    between two letters, where stripping can't remove it, and the message
    shows the control-character check refused the name, not another rule.
    """
    values = _valid_values(full_name=full_name)
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("full_name",)
    assert "must not contain control characters" in error["msg"]


def test_a_name_with_a_zero_width_non_joiner_is_accepted() -> None:
    """An invisible formatting character in the name is kept as given.

    The zero-width non-joiner is a formatting character, not a control
    character, and some scripts, Persian among them, need it inside names.
    The check must refuse control characters only.
    """
    full_name = "Ana‌Smith"
    values = _valid_values(full_name=full_name)
    data = UserCreate(**values)

    assert data.full_name == full_name


def test_the_password_is_kept_exactly_as_typed() -> None:
    """Spaces around the password are kept.

    They are part of the password; stripping them would lock the user out.
    """
    values = _valid_values(password=" padded password ")
    data = UserCreate(**values)

    assert data.password.get_secret_value() == " padded password "


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("x" * 15, id="15 characters"),
        pytest.param("x" * 128, id="128 characters"),
    ],
)
def test_a_password_at_the_length_limits_is_accepted(password: str) -> None:
    """Passwords of exactly 15 and 128 characters are accepted unchanged.

    The lengths are written out rather than read from the constants, so
    lowering the minimum below the 15 that NIST SP 800-63B-4 requires of a
    password that is the only sign-in factor fails here.
    """
    values = _valid_values(password=password)
    data = UserCreate(**values)

    assert data.password.get_secret_value() == password


def test_the_password_is_hidden_when_printed() -> None:
    """Printing the whole model never shows the password.

    The model is what ends up in logs and tracebacks, so this checks
    ``repr`` and ``str`` of the model, not just of the password field.
    """
    values = _valid_values(password="Correct-Password-1")
    data = UserCreate(**values)

    assert "Correct-Password-1" not in repr(data)
    assert "Correct-Password-1" not in str(data)


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("x" * 14, id="14 characters"),
        pytest.param("x" * 129, id="129 characters"),
    ],
)
def test_an_invalid_password_is_rejected(password: str) -> None:
    """Passwords of 14 and 129 characters fail on the ``password`` field."""
    values = _valid_values(password=password)
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    assert exc_info.value.errors()[0]["loc"] == ("password",)


def test_an_unknown_role_is_rejected() -> None:
    """A role that isn't a ``Role`` value fails on the ``role`` field."""
    values = _valid_values(role="superuser")
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    assert exc_info.value.errors()[0]["loc"] == ("role",)
