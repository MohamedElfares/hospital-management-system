"""Application settings loaded from environment variables.

Every setting comes from the process environment or, for local development,
from a ``.env`` file in the working directory, which is ``backend/.env``
because every documented command runs from ``backend/``. A variable set in
the environment wins over the same key in ``.env``. Values are validated
once at startup, so a missing secret, a wrong database driver, or an
unknown timezone stops the app with a clear message instead of failing
later during a request. Production values are set in the Render dashboard
and are never stored in the repository.
"""

# Decorator that caches a function's result, so settings are built only once.
from functools import lru_cache

# Attaches Field() options to a type; used for the lifetime limits and repr=False on the URLs.
from typing import Annotated

# Restricts a field to a fixed set of allowed string values.
from typing import Literal

# Loads an IANA timezone by name; used to reject unknown HOSPITAL_TIMEZONE values.
from zoneinfo import ZoneInfo

# Error raised by ZoneInfo when a timezone name does not exist.
from zoneinfo import ZoneInfoNotFoundError

# Declares field options: token lifetimes above zero, and URLs left out of repr().
from pydantic import Field

# String type that hides its value when printed or logged; used for the JWT secret.
from pydantic import SecretStr

# Validation context; tells the URL check which of the two variables it is checking.
from pydantic import ValidationInfo

# Decorator that registers a custom check on one or more fields.
from pydantic import field_validator

# Base class whose fields are filled from environment variables and the .env file.
from pydantic_settings import BaseSettings

# Typed options for the settings class, such as which .env file to read.
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """Validated configuration for one running instance of the API.

    Field names match environment variable names without regard to case, so
    ``database_url`` is read from ``DATABASE_URL``. Only the database URL
    and the JWT secret are required, because no default for them is safe;
    every other setting has a default that suits local development. An
    unknown key in ``.env`` is rejected when it has a value
    (``extra="forbid"``), so a misspelled variable fails loudly instead of
    being silently ignored; pydantic-settings skips unknown keys left
    empty. Validation errors print without the rejected value
    (``hide_input_in_errors=True``), because that value can be a database
    password or the signing secret. ``ValidationError.errors()`` still
    holds it, so that list must never be logged.

    Attributes:
        environment: Deployment environment. In production the refresh
            cookie is marked ``Secure``. Error responses don't depend on it:
            an unexpected error gets the same generic message in every
            environment, and its traceback goes only to the log.
        database_url: SQLAlchemy URL for PostgreSQL through psycopg 3. It
            contains the database password, so it must never be logged, and
            ``repr()`` leaves it out.
        test_database_url: SQLAlchemy URL for the database the test suite
            uses, left out of ``repr()`` like ``database_url``. Unset outside
            development and CI; the test setup fails loudly when it is
            missing, so tests can never run against the development database
            by accident.
        jwt_secret_key: Key used to sign HS256 access tokens. At least 32
            characters, and different in every environment.
        access_token_expire_minutes: Lifetime of an access token in minutes.
            Must be greater than zero.
        refresh_token_expire_days: Lifetime of a refresh token in days. Must
            be greater than zero.
        hospital_timezone: IANA timezone name used for business rules such as
            "today" and appointment slot boundaries. Timestamps are still
            stored in UTC.
        log_level: Minimum level of log records that are written.
        demo_mode: Whether demo accounts are protected from being
            deactivated or having their passwords changed. Nothing reads it
            yet: that protection arrives with ``seed-demo`` in Milestone 1.7.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        hide_input_in_errors=True,
    )

    environment: Literal["local", "test", "production"] = "local"
    database_url: Annotated[str, Field(repr=False)]
    test_database_url: Annotated[str | None, Field(repr=False)] = None
    jwt_secret_key: SecretStr
    access_token_expire_minutes: Annotated[int, Field(gt=0)] = 15
    refresh_token_expire_days: Annotated[int, Field(gt=0)] = 7
    hospital_timezone: str = "Asia/Dubai"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    demo_mode: bool = False

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _check_database_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        """Require the PostgreSQL psycopg 3 driver in the database URL.

        The whole design depends on PostgreSQL features (partial unique
        indexes, row locks, sequences), and the app uses psycopg 3, so any
        other dialect or driver is a configuration mistake. Neon's
        ``postgresql://`` connection strings must be rewritten to this
        prefix before they are used. ``TEST_DATABASE_URL`` is optional, so
        ``None`` is accepted and left for the test setup to reject.

        Args:
            value: The raw ``DATABASE_URL`` or ``TEST_DATABASE_URL`` value,
                or ``None`` when no test database is configured.
            info: Pydantic's validation context. ``info.field_name`` says
                which of the two URLs is being checked, so the message can
                name it.

        Returns:
            The unchanged URL.

        Raises:
            ValueError: If the URL does not start with
                ``postgresql+psycopg://``. Neither this message nor
                pydantic's printed error includes the URL, because it
                contains the password.
        """
        if value is None:
            return value
        if not value.startswith("postgresql+psycopg://"):
            field_name = info.field_name.upper()
            raise ValueError(f"{field_name} must start with postgresql+psycopg://")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def _check_jwt_secret_key(cls, value: SecretStr) -> SecretStr:
        """Require a JWT signing secret of at least 32 characters.

        A short HS256 secret can be brute-forced, which would let an attacker
        forge access tokens for any user. The ``.env.example`` placeholder is
        deliberately shorter than 32 characters, so copying the example file
        without generating a real secret fails at startup.

        Args:
            value: The ``JWT_SECRET_KEY`` value, wrapped so it stays hidden.

        Returns:
            The unchanged secret.

        Raises:
            ValueError: If the secret has fewer than 32 characters. Neither
                this message nor pydantic's printed error includes the
                secret.
        """
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return value

    @field_validator("hospital_timezone")
    @classmethod
    def _check_hospital_timezone(cls, value: str) -> str:
        """Require a timezone name that exists in the IANA database.

        Business rules such as "check-in only on the appointment date" depend
        on this timezone, so an invalid name must stop the app at startup.
        On Windows, the ``tzdata`` package supplies the timezone database.

        Args:
            value: The raw ``HOSPITAL_TIMEZONE`` value, such as
                ``"Asia/Dubai"``.

        Returns:
            The unchanged timezone name.

        Raises:
            ValueError: If the name is unknown (``ZoneInfoNotFoundError``) or
                malformed, such as an empty string or a path (``ValueError``
                from ``ZoneInfo``). The original error is kept as the cause.
        """
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"HOSPITAL_TIMEZONE {value!r} is not a valid IANA timezone") from exc
        return value

    @property
    def is_production(self) -> bool:
        """Whether the app is running in production.

        This is derived from ``environment`` rather than stored separately,
        so the two can never disagree, and it is not read from an environment
        variable. Security-sensitive code checks it, such as the code that
        marks the refresh cookie ``Secure``.

        Returns:
            ``True`` only when ``environment`` is ``"production"``.
        """
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Build the settings once and return the same instance afterward.

    Settings are built on the first call, not when this module is imported,
    so importing ``app.core.config`` never fails because a setting is
    missing or invalid. ``app.db.session`` calls this function at import
    time to build the engine, so importing that module, directly or through
    the app, does need valid settings. The cache makes every later call
    cheap and consistent. Tests that need different values can call
    ``get_settings.cache_clear()`` after changing the environment.

    Returns:
        The validated application settings.

    Raises:
        pydantic.ValidationError: If a required variable is missing,
            ``.env`` has an unknown key with a value, or any value fails
            validation.

    Example:
        ``database_url = get_settings().database_url``
    """
    return Settings()  # type: ignore[call-arg]
