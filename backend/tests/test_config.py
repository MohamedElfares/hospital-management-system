"""Tests for ``Settings``, the validated configuration in ``app/core/config.py``.

These are unit tests: they build ``Settings`` directly, never through the
cached ``get_settings``, with no database and no request. The
``isolated_environment`` fixture removes every settings variable from the
environment, and ``_make_settings`` reads no ``.env`` file and supplies
the two required values, so each test sees only what it passes and
changes only the setting it is about. The tests check the defaults; the
two settings without a default; the values each setting refuses, which
are an environment or a log level outside its list, a database URL without
the psycopg 3 driver, a JWT secret under 32 characters, a token lifetime
of zero or less, and an unknown or malformed timezone; an unknown key in
``.env``; that neither a printed error nor the settings' ``repr`` shows a
database password or the secret; and ``is_production``. What a setting
changes is tested with the code that reads it: the refresh cookie's
``Secure`` flag in ``tests/test_security.py``, the token lifetimes there
and in ``tests/test_auth_service.py`` and ``tests/test_auth_api.py``, the
log level in ``tests/test_logging.py``, and the test database in
``tests/test_database.py``.
"""

# Type of tmp_path, the temporary folder the unknown-key test writes its .env file in.
from pathlib import Path

# Test framework: the autouse fixture, parametrize, raises, and the monkeypatch type.
import pytest

# What Settings raises for a refused value; its errors() name the setting that failed.
from pydantic import ValidationError

# The settings class under test, built directly in each test.
from app.core.config import Settings

# The password each rejected value below holds, which no printed error may show.
LEAKED_PASSWORD = "Leaked-Password-1"

# A URL with Neon's postgresql:// prefix, which the URL check refuses, holding the password.
# Kept short on purpose: pydantic prints a value of up to 50 characters, quotes included, in
# full, and cuts a longer one in the middle, which could hide a leaked password by accident.
LEAKED_DATABASE_URL = f"postgresql://u:{LEAKED_PASSWORD}@h/db"

# The same for TEST_DATABASE_URL, which goes through the same check.
LEAKED_TEST_DATABASE_URL = f"postgresql://u:{LEAKED_PASSWORD}@h/test"

# A URL the check accepts: the development database's, as .env.example and CI give it.
VALID_DATABASE_URL = "postgresql+psycopg://hms:hms@127.0.0.1:5432/hms"

# Over the 32-character minimum, and plainly not a real secret.
VALID_JWT_SECRET_KEY = "test-only-signing-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every settings variable from the environment for each test.

    CI sets ``DATABASE_URL``, ``TEST_DATABASE_URL``, ``JWT_SECRET_KEY``,
    ``ENVIRONMENT``, and ``LOG_LEVEL`` as real environment variables, and
    ``Settings`` reads those even when no ``.env`` file is used: left in
    place, CI's ``ENVIRONMENT=test`` and ``LOG_LEVEL=WARNING`` would fail
    the defaults test. Clearing them means each test sees only the values
    it passes. Each variable is removed under its upper-case name, the
    spelling CI and ``.env.example`` use. pydantic-settings matches names
    in any case, and so does the environment on Windows, where that
    removes every spelling; on Linux, a variable spelled in lower case
    would survive and still reach the settings.

    Args:
        monkeypatch: pytest's helper for changes that are undone after the
            test.
    """
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


def _make_settings(**overrides: object) -> Settings:
    """Build settings from keyword values only, with valid required ones.

    ``_env_file=None`` keeps the developer's ``.env`` out of the test, and
    ``isolated_environment`` has already removed the settings variables
    from the environment, so only the values given here count. It fills
    in a valid database URL and JWT secret, the two settings without a
    default of their own; each test passes just the setting it is about.

    Args:
        **overrides: Settings that replace or add to the valid defaults.

    Returns:
        The validated settings.

    Raises:
        ValidationError: If any value is rejected, which is what most tests
            expect.
    """
    values: dict[str, object] = {
        "database_url": VALID_DATABASE_URL,
        "jwt_secret_key": VALID_JWT_SECRET_KEY,
        **overrides,
    }

    return Settings(_env_file=None, **values)


def test_only_the_required_settings_give_the_documented_defaults() -> None:
    """With only the two required values set, every other setting has its default.

    The defaults are the values ``.env.example`` lists, except that
    ``TEST_DATABASE_URL`` is unset, where the file names the test database
    for local development. The token lifetimes matter most, because plan
    §8.1 fixes them at 15 minutes and 7 days, and ``TEST_DATABASE_URL``
    must stay unset rather than fall back to the development database.
    This is also the positive control: the other tests start from the same
    baseline and change only what they are about, so a failure points at
    that change.
    """
    settings = _make_settings()

    assert settings.environment == "local"
    assert settings.database_url == VALID_DATABASE_URL
    assert settings.test_database_url is None
    assert settings.jwt_secret_key.get_secret_value() == VALID_JWT_SECRET_KEY
    assert settings.access_token_expire_minutes == 15
    assert settings.refresh_token_expire_days == 7
    assert settings.hospital_timezone == "Asia/Dubai"
    assert settings.log_level == "INFO"
    assert settings.demo_mode is False


def test_database_url_and_jwt_secret_key_are_required() -> None:
    """Without the database URL and the JWT secret, the settings refuse to load.

    The error names exactly those two settings, each as missing. No default
    would be safe for either: a default secret would let anyone who reads
    the code sign access tokens, and a default URL could point the
    application at the wrong database.
    """
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    errors = exc_info.value.errors()

    assert [(error["loc"], error["type"]) for error in errors] == [
        (("database_url",), "missing"),
        (("jwt_secret_key",), "missing"),
    ]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        pytest.param("environment", "prod", id="environment"),
        pytest.param("log_level", "VERBOSE", id="log-level"),
    ],
)
def test_settings_with_a_fixed_set_of_values_reject_any_other(field_name: str, value: str) -> None:
    """``ENVIRONMENT`` and ``LOG_LEVEL`` accept only their listed values.

    A typo such as ``prod`` must stop startup: read as anything other than
    production, it would quietly drop the refresh cookie's ``Secure`` flag.
    ``logging`` refuses ``VERBOSE`` too, but only when the application
    configures it, and its message doesn't name ``LOG_LEVEL``. Each value
    gets a single ``literal_error`` on its own setting.
    """
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(**{field_name: value})

    errors = exc_info.value.errors()

    assert len(errors) == 1
    assert errors[0]["loc"] == (field_name,)
    assert errors[0]["type"] == "literal_error"


@pytest.mark.parametrize(
    "database_url",
    [
        pytest.param("postgresql://hms:hms@127.0.0.1:5432/hms", id="neon-style-prefix"),
        pytest.param("postgres://hms:hms@127.0.0.1:5432/hms", id="short-scheme"),
        pytest.param("postgresql+asyncpg://hms:hms@127.0.0.1:5432/hms", id="other-driver"),
        pytest.param("sqlite:///hms.db", id="sqlite"),
    ],
)
def test_database_url_without_the_psycopg_driver_is_rejected(database_url: str) -> None:
    """A database URL for another dialect or driver stops startup, naming the variable.

    The design depends on PostgreSQL features and on psycopg 3. Neon's
    connection string starts with ``postgresql://``, so forgetting to
    rewrite its prefix is the likeliest mistake of all. Each URL gets the
    one error, whose message names ``DATABASE_URL`` and the prefix it
    needs.
    """
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(database_url=database_url)

    errors = exc_info.value.errors()

    assert len(errors) == 1
    assert errors[0]["loc"] == ("database_url",)
    assert errors[0]["msg"] == "Value error, DATABASE_URL must start with postgresql+psycopg://"


def test_test_database_url_with_the_wrong_driver_names_its_own_variable() -> None:
    """A bad test database URL is reported as ``TEST_DATABASE_URL``, not ``DATABASE_URL``.

    Both URLs go through one check, so the message has to name the one
    that is wrong, or the developer edits the wrong line.
    """
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(test_database_url="postgresql://hms:hms@127.0.0.1:5432/hms_test")

    errors = exc_info.value.errors()

    assert len(errors) == 1
    assert errors[0]["loc"] == ("test_database_url",)
    assert errors[0]["msg"] == (
        "Value error, TEST_DATABASE_URL must start with postgresql+psycopg://"
    )


def test_jwt_secret_key_shorter_than_32_characters_is_rejected() -> None:
    """A 31-character signing secret stops startup.

    A short HS256 secret can be brute-forced, and whoever finds it can
    forge an access token for any user (plan §15: at least 32 characters).
    """
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(jwt_secret_key="k" * 31)

    errors = exc_info.value.errors()

    assert len(errors) == 1
    assert errors[0]["loc"] == ("jwt_secret_key",)
    assert errors[0]["msg"] == "Value error, JWT_SECRET_KEY must be at least 32 characters long"


def test_jwt_secret_key_of_exactly_32_characters_is_accepted() -> None:
    """A 32-character secret is the shortest one accepted, so the limit is exact."""
    settings = _make_settings(jwt_secret_key="k" * 32)

    assert settings.jwt_secret_key.get_secret_value() == "k" * 32


@pytest.mark.parametrize("field_name", ["access_token_expire_minutes", "refresh_token_expire_days"])
@pytest.mark.parametrize("lifetime", [0, -1])
def test_token_lifetimes_must_be_greater_than_zero(field_name: str, lifetime: int) -> None:
    """A token lifetime of zero or less stops startup.

    A lifetime of zero would issue tokens that have already expired, since
    both kinds count as expired from their expiry time on, so no one could
    stay signed in, and a negative lifetime means nothing. Both are
    refused, for the access token and the refresh token alike.
    """
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(**{field_name: lifetime})

    errors = exc_info.value.errors()

    assert len(errors) == 1
    assert errors[0]["loc"] == (field_name,)
    assert errors[0]["type"] == "greater_than"


@pytest.mark.parametrize(
    "hospital_timezone",
    [
        pytest.param("Mars/Olympus_Mons", id="unknown-name"),
        pytest.param("", id="empty"),
        pytest.param("../etc/passwd", id="path"),
    ],
)
def test_unknown_or_malformed_hospital_timezone_is_rejected(hospital_timezone: str) -> None:
    """An unknown or malformed timezone name stops startup.

    The unknown name fails the lookup in the IANA database, and ``ZoneInfo``
    refuses the empty string and the path as keys before any lookup, so the
    name can never point the timezone loader at another file; the validator
    turns both errors into the same refusal. From Milestone 1.4, "today"
    and the appointment rules, such as check-in only on the appointment
    date, depend on the name, so a typo must fail at once rather than on
    the first booking.
    """
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(hospital_timezone=hospital_timezone)

    errors = exc_info.value.errors()

    assert len(errors) == 1
    assert errors[0]["loc"] == ("hospital_timezone",)
    assert errors[0]["type"] == "value_error"


def test_unknown_key_with_a_value_in_the_env_file_is_rejected(tmp_path: Path) -> None:
    """A misspelled variable in ``.env`` stops startup instead of being ignored.

    Ignored, ``HOSPITAL_TIMEZON`` would leave the real setting at its
    default without a word. The file is written to a temporary folder, so
    the developer's own ``.env`` is never read. The key has a value on
    purpose: pydantic-settings skips unknown keys that are left empty.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("HOSPITAL_TIMEZON=Europe/London\n", encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=env_file,
            database_url=VALID_DATABASE_URL,
            jwt_secret_key=VALID_JWT_SECRET_KEY,
        )

    errors = exc_info.value.errors()

    assert len(errors) == 1
    assert errors[0]["loc"] == ("hospital_timezon",)
    assert errors[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    ("field_name", "rejected_value"),
    [
        pytest.param("database_url", LEAKED_DATABASE_URL, id="database-url"),
        pytest.param("test_database_url", LEAKED_TEST_DATABASE_URL, id="test-database-url"),
        pytest.param("jwt_secret_key", LEAKED_PASSWORD, id="short-jwt-secret"),
    ],
)
def test_settings_errors_never_print_the_rejected_value(
    field_name: str,
    rejected_value: str,
) -> None:
    """A rejected URL or secret never appears in the printed validation error.

    A startup error goes to the server's log, which on Render anyone with
    dashboard access can read, so a Neon URL with the wrong prefix must not
    print its password, and a short secret must not print itself. pydantic
    shows the input unless ``hide_input_in_errors`` is set. Its
    ``errors()`` list still carries the input, so nothing may log that
    list. Each value is short enough that pydantic would print it in full,
    so the test can't pass just because the value was cut.
    """
    assert len(repr(rejected_value)) <= 50, "pydantic would shorten this value"

    with pytest.raises(ValidationError) as exc_info:
        _make_settings(**{field_name: rejected_value})

    assert exc_info.value.errors()[0]["loc"] == (field_name,)
    assert LEAKED_PASSWORD not in str(exc_info.value)
    assert LEAKED_PASSWORD not in repr(exc_info.value)


def test_settings_repr_hides_the_database_passwords_and_the_secret() -> None:
    """Printing the settings shows neither database password nor the JWT secret.

    The settings object can end up in a traceback or a debug print, so the
    two URLs are left out of its ``repr`` and the secret is masked; ``str``
    hides them the same way, and the test reads both. The values themselves
    stay readable, because the application connects with them.
    """
    settings = _make_settings(
        database_url="postgresql+psycopg://hms:Leaked-Password-1@db.example.com/hms",
        test_database_url="postgresql+psycopg://hms:Leaked-Password-2@db.example.com/hms_test",
        jwt_secret_key="Leaked-Secret-Key-0123456789abcdef",
    )

    shown = f"{settings!r} {settings}"

    assert "Leaked-Password-1" not in shown
    assert "Leaked-Password-2" not in shown
    assert "Leaked-Secret-Key" not in shown
    assert settings.test_database_url == (
        "postgresql+psycopg://hms:Leaked-Password-2@db.example.com/hms_test"
    )


@pytest.mark.parametrize(
    ("environment", "is_production"),
    [("local", False), ("test", False), ("production", True)],
)
def test_is_production_only_in_production(environment: str, is_production: bool) -> None:
    """Only ``ENVIRONMENT=production`` counts as production.

    It decides whether the refresh cookie is marked ``Secure``, so the
    ``test`` environment CI uses must not count as production, and
    production must never count as anything else.
    """
    settings = _make_settings(environment=environment)

    assert settings.is_production is is_production
