import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import LoginForm
from app.modules.auth.schemas import PasswordChange
from app.modules.users.schemas import PASSWORD_MAX_LENGTH
from app.modules.users.schemas import PASSWORD_MIN_LENGTH

CURRENT_PASSWORD = "Old.Password123"
NEW_PASSWORD = "New.Password123"


def _valid_values(**overrides: str) -> dict[str, str]:
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
    values = _valid_values()
    data = PasswordChange(**values)

    assert data.current_password.get_secret_value() == values["current_password"]
    assert data.new_password.get_secret_value() == values["new_password"]


@pytest.mark.parametrize(
    "new_password",
    [
        pytest.param("x" * PASSWORD_MIN_LENGTH, id=f"{PASSWORD_MIN_LENGTH} characters"),
        pytest.param("x" * PASSWORD_MAX_LENGTH, id=f"{PASSWORD_MAX_LENGTH} characters"),
    ],
)
def test_the_new_password_at_the_length_limits_is_accepted(new_password: str) -> None:
    """New passwords of exactly the rule's shortest and longest lengths are accepted unchanged.

    These are the last valid lengths on each side, built from the shared
    constants so the test follows the rule if it ever changes, and the IDs
    are built from them too, so they always name the lengths tested. The
    rule's values are pinned by the ``UserCreate`` tests in
    ``tests/test_user_schemas.py``.
    """
    values = _valid_values(new_password=new_password)
    data = PasswordChange(**values)

    assert data.new_password.get_secret_value() == values["new_password"]


@pytest.mark.parametrize(
    "new_password",
    [
        pytest.param("x" * (PASSWORD_MIN_LENGTH - 1), id=f"{PASSWORD_MIN_LENGTH - 1} characters"),
        pytest.param("x" * (PASSWORD_MAX_LENGTH + 1), id=f"{PASSWORD_MAX_LENGTH + 1} characters"),
    ],
)
def test_an_invalid_new_password_is_rejected(new_password: str) -> None:
    """New passwords one character outside the rule's limits fail on the ``new_password`` field.

    These are the first invalid lengths on each side, so a limit that is
    off by one in either direction fails one of the two boundary tests.
    """
    values = _valid_values(new_password=new_password)

    with pytest.raises(ValidationError) as exc_info:
        PasswordChange(**values)

    assert any(error["loc"] == ("new_password",) for error in exc_info.value.errors())


def test_a_short_current_password_is_accepted() -> None:
    """A one-character current password passes validation.

    The current password is checked against the stored hash, not against
    the rule, so the schema sets no minimum; a wrong one is rejected by
    the service instead.
    """
    values = _valid_values(current_password="W")
    data = PasswordChange(**values)

    assert data.current_password.get_secret_value() == "W"


def test_a_too_long_current_password_is_rejected() -> None:
    """A current password of 129 characters fails on the ``current_password`` field.

    No stored password can be longer than 128 characters, so a longer one
    can never be right, and rejecting it here spares the server an Argon2
    check on input of any size.
    """
    values = _valid_values(current_password="x" * (PASSWORD_MAX_LENGTH + 1))

    with pytest.raises(ValidationError) as exc_info:
        PasswordChange(**values)

    assert any(error["loc"] == ("current_password",) for error in exc_info.value.errors())


def test_both_passwords_are_hidden_when_printed() -> None:
    """Printing the model never shows either password.

    The model is what ends up in logs and tracebacks, so ``repr`` and
    ``str`` of the whole model must hide both values.
    """
    values = _valid_values()
    data = PasswordChange(**values)

    assert NEW_PASSWORD not in str(data)
    assert NEW_PASSWORD not in repr(data)
    assert CURRENT_PASSWORD not in str(data)
    assert CURRENT_PASSWORD not in repr(data)


def test_the_login_form_shows_no_credentials_when_printed() -> None:
    """Printing the sign-in form shows neither the password nor the email.

    The form keeps the password as a plain ``str``, as FastAPI's form class
    does, so it stays out of logs only because the form is a plain class,
    whose ``repr`` and ``str`` show no field values. A dataclass or a model
    with the same fields would print both, and this test would fail.
    """
    login_form = LoginForm(username="test@example.com", password=CURRENT_PASSWORD)

    assert CURRENT_PASSWORD not in repr(login_form)
    assert CURRENT_PASSWORD not in str(login_form)
    assert "test@example.com" not in repr(login_form)
    assert "test@example.com" not in str(login_form)
