"""Tests for ``UserCreate``, the validated input for a new user account.

These are unit tests: they build the schema directly, with no database and
no request, as ``create-admin`` builds it. ``_valid_values`` supplies input
that passes every rule, and each test changes one field. The email comes
out lowercase, and a malformed one is refused. The full name is stripped
of surrounding whitespace, tabs and line breaks included, before it is
checked, must be 1 to 255 characters long, and is refused when it holds a
control character, while a zero-width non-joiner is kept. The password is
kept exactly as typed, must be 15 to 128 characters long, and stays hidden
when the model is printed. The role must be a ``Role`` value. Each refusal is
checked by the field it names. The same email rule at sign-in is tested
in ``tests/test_user_service.py``; ``PasswordChange``, which shares the
password rule, in ``tests/test_auth_schemas.py``; and ``UserRead``, through
``GET /auth/me``, in ``tests/test_auth_api.py``.
"""

# Test framework: parametrize for the values each rule accepts or refuses, and raises.
import pytest

# What the schema raises for invalid input; its errors() name the field that failed.
from pydantic import ValidationError

# The role enum; supplies the valid input's role.
from app.core.permissions import Role

# The input schema under test.
from app.modules.users.schemas import UserCreate


def _valid_values(**overrides: object) -> dict[str, object]:
    """Return valid ``UserCreate`` input, replacing any given fields.

    Each test changes only the field it is about, so a failure points at
    that field. The defaults pass every rule: a lowercase email, a plain
    name, an 18-character password, and the Doctor role.

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
    """An email typed in any letter case comes out lowercase.

    email-validator lowercases only the domain, so the capital in ``Test``
    shows that the ``Email`` rule lowercases the local part too, as the
    users table's CHECK requires; an address already in lowercase comes
    out unchanged.
    """
    values = _valid_values(email=email)
    expected_email = "test@example.com"
    data = UserCreate(**values)
    assert data.email == expected_email


def test_a_malformed_email_is_rejected() -> None:
    """An email whose domain has no dot fails on the ``email`` field.

    email-validator refuses it: the part after the @-sign must have a
    period.
    """
    values = _valid_values(email="test@example")
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    assert exc_info.value.errors()[0]["loc"] == ("email",)


def test_the_name_is_stripped_of_surrounding_spaces() -> None:
    """Spaces around the full name are removed.

    A name typed or pasted with stray spaces is stored as the name alone.
    """
    values = _valid_values(full_name="  Ana  ")
    data = UserCreate(**values)

    assert data.full_name == "Ana"


@pytest.mark.parametrize(
    "full_name",
    [
        pytest.param("Ana\n", id="trailing-line-break"),
        pytest.param("Ana\r\n", id="trailing-crlf"),
        pytest.param("\tAna\t", id="surrounding-tabs"),
    ],
)
def test_a_tab_or_line_break_around_the_name_is_stripped(full_name: str) -> None:
    """A tab or a line break around the name is stripped, not refused.

    Both are control characters, which a name may not contain, but they
    are whitespace too, and the name is stripped before
    ``_reject_control_characters`` runs, as its docstring says. So a name
    pasted with a trailing line break, a Windows line ending included, is
    stored as the name alone, where a check that ran before the stripping
    would refuse it.
    """
    values = _valid_values(full_name=full_name)
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
    """Names of exactly 1 and 255 characters are accepted unchanged.

    255 is the size of the ``users.full_name`` column, which the schema's
    maximum matches.
    """
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
    At the edges, a tab or a line break is stripped instead, as
    ``test_a_tab_or_line_break_around_the_name_is_stripped`` checks.
    """
    values = _valid_values(full_name=full_name)
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("full_name",)
    assert "must not contain control characters" in error["msg"]


def test_a_name_with_a_zero_width_non_joiner_is_accepted() -> None:
    """An invisible formatting character in the name is kept as given.

    The value holds U+200C, the zero-width non-joiner, between ``Ana`` and
    ``Smith``. It is a formatting character, not a control character, and
    some scripts, Persian among them, need it inside names. The check must
    refuse control characters only.
    """
    full_name = "Ana‌Smith"
    values = _valid_values(full_name=full_name)
    data = UserCreate(**values)

    assert data.full_name == full_name


def test_the_password_is_kept_exactly_as_typed() -> None:
    """Spaces around the password are kept.

    They are part of the password. Sign-in checks the typed password with
    its spaces, so stripping them here would lock the user out.
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
    raising the minimum above 15 or lowering the maximum below 128 fails
    here; lowering the minimum fails ``test_an_invalid_password_is_rejected``.
    """
    values = _valid_values(password=password)
    data = UserCreate(**values)

    assert data.password.get_secret_value() == password


def test_the_password_is_hidden_when_printed() -> None:
    """Printing the whole model never shows the password.

    A model can reach a log line, or a traceback that shows local
    variables, so this checks ``repr`` and ``str`` of the model, not just
    of the password field.
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
    """Passwords of 14 and 129 characters fail on the ``password`` field.

    The lengths are written out, so lowering the minimum below the 15 that
    NIST SP 800-63B-4 requires of a password that is the only sign-in
    factor, as every password here is, fails here, as does raising the
    maximum above 128.
    """
    values = _valid_values(password=password)
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    assert exc_info.value.errors()[0]["loc"] == ("password",)


def test_an_unknown_role_is_rejected() -> None:
    """A role that isn't a ``Role`` value fails on the ``role`` field.

    The role decides which permissions an account gets (plan §6), so only
    the eight roles ``Role`` defines are accepted.
    """
    values = _valid_values(role="superuser")
    with pytest.raises(ValidationError) as exc_info:
        UserCreate(**values)

    assert exc_info.value.errors()[0]["loc"] == ("role",)
