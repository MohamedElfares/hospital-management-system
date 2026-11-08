"""Tests for the auth schemas: ``PasswordChange`` and the sign-in form.

These are unit tests: they build the schemas directly, with no database and
no request. ``_valid_values`` supplies a password change that passes every
rule, and each test changes one field. The new password follows the shared
password rule, and the boundary tests build their lengths from the rule's
constants, whose values the ``UserCreate`` tests in
``tests/test_user_schemas.py`` pin. The current password has only the
maximum, so a short one passes, and both passwords stay hidden when the
model is printed. ``LoginForm`` shows neither the email nor the password
when printed. Each refusal is checked by the field it names. The form's
length limits and the 422 bodies are tested through the API in
``tests/test_auth_api.py``, and the service's refusals of a wrong current
password and an unchanged one in ``tests/test_auth_service.py``.
"""

# Test framework: parametrize for the lengths at each limit, and raises.
import pytest

# What the schema raises for invalid input; its errors() name the field that failed.
from pydantic import ValidationError

# The sign-in form; only what it shows when printed is tested here.
from app.modules.auth.schemas import LoginForm

# The password change input schema under test.
from app.modules.auth.schemas import PasswordChange

# Longest password the rule allows; the boundary lengths and the current password's limit.
from app.modules.users.schemas import PASSWORD_MAX_LENGTH

# Shortest password the rule allows; the new password's boundary lengths.
from app.modules.users.schemas import PASSWORD_MIN_LENGTH

CURRENT_PASSWORD = "Old.Password123"
NEW_PASSWORD = "New.Password123"


def _valid_values(**overrides: str) -> dict[str, str]:
    """Return valid ``PasswordChange`` input, replacing any given fields.

    Both defaults pass every rule, so each test changes only the field it
    is about, and a failure points at that field. The new password is 15
    characters, the rule's minimum, so raising the minimum means
    lengthening it too. The two passwords differ, so a test can tell which
    one leaked or was swapped. The schema doesn't compare them; the service
    refuses a new password equal to the current one.

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
    """Valid input is accepted, and both passwords come back as given.

    Each value is read back with ``get_secret_value()``, so a schema that
    swapped the two fields, or changed a character of either, fails here.
    Neither default has a space at either end, so this can't see a schema
    that strips them, which would lock out a user whose password has one.
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
    the rule, so the schema sets no minimum, and a password set under an
    older, shorter minimum can still be changed. A wrong one, however
    short, is refused by the service instead. A minimum of one character
    would still pass here: no test types an empty current password.
    """
    values = _valid_values(current_password="W")
    data = PasswordChange(**values)

    assert data.current_password.get_secret_value() == "W"


def test_a_too_long_current_password_is_rejected() -> None:
    """A current password of 129 characters fails on the ``current_password`` field.

    No password can be set longer than 128 characters, the rule's maximum,
    so a longer one can never be right, and refusing it here spares the
    service an Argon2 check that could only fail. Only the length one over
    the limit is tested: no test sends a current password of exactly 128
    characters, so a maximum one lower, which would refuse a user's own
    128-character password, would go unseen.
    """
    values = _valid_values(current_password="x" * (PASSWORD_MAX_LENGTH + 1))

    with pytest.raises(ValidationError) as exc_info:
        PasswordChange(**values)

    assert any(error["loc"] == ("current_password",) for error in exc_info.value.errors())


def test_both_passwords_are_hidden_when_printed() -> None:
    """Printing the model never shows either password.

    A model can reach a log line, or a traceback that shows local
    variables, so this checks ``repr`` and ``str`` of the whole model, not
    just of each field. Both fields are ``SecretStr``, which shows
    ``**********`` in place of the value.
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
