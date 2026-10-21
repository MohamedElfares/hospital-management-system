import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import PasswordChange
from app.modules.users.schemas import PASSWORD_MAX_LENGTH
from app.modules.users.schemas import PASSWORD_MIN_LENGTH

CURRENT_PASSWORD = "Old.Password123"
NEW_PASSWORD = "New.Password123"


def valid_password_change(**overrides: str) -> dict[str, str]:
    """Return valid ``PasswordChange`` input, replacing any given fields.

    Both defaults are valid, so each test changes only the field it is
    about, and a failure points at that field. The two passwords differ, so
    a test can tell which one leaked or was swapped. The schema doesn't
    compare them; the service rejects a new password equal to the current
    one.

    Args:
        **overrides: Field values that replace the defaults.

    Returns:
        A dict to unpack into ``PasswordChange``.
    """
    values = {
        "current_password": CURRENT_PASSWORD,
        "new_password": NEW_PASSWORD,
    }

    values.update(overrides)
    return values


def test_a_valid_password_change_is_accepted() -> None:
    """Valid input is accepted, and both passwords are kept exactly as typed.

    Each value is read back with ``get_secret_value()``, so a schema that
    stripped, swapped, or rewrote a password fails here.
    """
    data = valid_password_change()
    password_change = PasswordChange(**data)

    assert password_change.current_password.get_secret_value() == data["current_password"]
    assert password_change.new_password.get_secret_value() == data["new_password"]


@pytest.mark.parametrize(
    "new_password",
    [
        pytest.param("x" * PASSWORD_MIN_LENGTH, id="12 characters"),
        pytest.param("x" * PASSWORD_MAX_LENGTH, id="128 characters"),
    ],
)
def test_the_new_password_at_the_length_limits_is_accepted(new_password: str) -> None:
    """New passwords of exactly 12 and 128 characters are accepted unchanged.

    These are the last valid lengths on each side, built from the shared
    constants so the test follows the rule if it ever changes.
    """
    data = valid_password_change(new_password=new_password)
    password_change = PasswordChange(**data)

    assert password_change.new_password.get_secret_value() == data["new_password"]


@pytest.mark.parametrize(
    "new_password",
    [
        pytest.param("x" * (PASSWORD_MIN_LENGTH - 1), id="11 characters"),
        pytest.param("x" * (PASSWORD_MAX_LENGTH + 1), id="129 characters"),
    ],
)
def test_an_invalid_new_password_is_rejected(new_password: str) -> None:
    """New passwords of 11 and 129 characters fail on the ``new_password`` field.

    These are the first invalid lengths on each side, so a limit that is
    off by one in either direction fails one of the two boundary tests.
    """
    data = valid_password_change(new_password=new_password)

    with pytest.raises(ValidationError) as exc_info:
        PasswordChange(**data)

    assert any(error["loc"] == ("new_password",) for error in exc_info.value.errors())


def test_a_short_current_password_is_accepted() -> None:
    """A one-character current password passes validation.

    The current password is checked against the stored hash, not against
    the rule, so the schema sets no minimum; a wrong one is rejected by
    the service instead.
    """
    data = valid_password_change(current_password="W")
    password_change = PasswordChange(**data)

    assert password_change.current_password.get_secret_value() == "W"


def test_a_too_long_current_password_is_rejected() -> None:
    """A current password of 129 characters fails on the ``current_password`` field.

    No stored password can be longer than 128 characters, so a longer one
    can never be right, and rejecting it here spares the server an Argon2
    check on input of any size.
    """
    data = valid_password_change(current_password="x" * (PASSWORD_MAX_LENGTH + 1))

    with pytest.raises(ValidationError) as exc_info:
        PasswordChange(**data)

    assert any(error["loc"] == ("current_password",) for error in exc_info.value.errors())


def test_both_passwords_are_hidden_when_printed() -> None:
    """Printing the model never shows either password.

    The model is what ends up in logs and tracebacks, so ``repr`` and
    ``str`` of the whole model must hide both values.
    """
    data = valid_password_change()
    password_change = PasswordChange(**data)

    assert NEW_PASSWORD not in str(password_change)
    assert NEW_PASSWORD not in repr(password_change)
    assert CURRENT_PASSWORD not in str(password_change)
    assert CURRENT_PASSWORD not in repr(password_change)
