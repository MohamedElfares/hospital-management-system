"""Application settings loaded from environment variables.

Every setting comes from the process environment or, for local development,
from ``backend/.env``. Values are validated once at startup, so a missing
secret, a wrong database driver, or an unknown timezone stops the app with a
clear message instead of failing later during a request. Production values
are set in the Render dashboard and are never stored in the repository.
"""

# Decorator that caches a function's result, so settings are built only once.
from functools import lru_cache

# Attaches extra metadata (constraints, NoDecode) to a field's type.
from typing import Annotated

# Restricts a field to a fixed set of allowed string values.
from typing import Literal

# Loads an IANA timezone by name; used to reject unknown HOSPITAL_TIMEZONE values.
from zoneinfo import ZoneInfo

# Error raised by ZoneInfo when a timezone name does not exist.
from zoneinfo import ZoneInfoNotFoundError

# Declares field constraints, such as token lifetimes greater than zero.
from pydantic import Field

# String type that hides its value when printed or logged; used for the JWT secret.
from pydantic import SecretStr

# Decorator that registers custom checks and conversions for individual fields.
from pydantic import field_validator

# Base class whose fields are filled from environment variables and the .env file.
from pydantic_settings import BaseSettings

# Stops pydantic-settings from parsing CORS_ORIGINS as JSON, so it can be split on commas.
from pydantic_settings import NoDecode

# Typed options for the settings class, such as which .env file to read.
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """Validated configuration for one running instance of the API.

    Field names match environment variable names without regard to case, so
    ``database_url`` is read from ``DATABASE_URL``. Only the database URL
    and the JWT secret are required, because no default for them is safe;
    every other setting has a development-friendly default from plan §15.
    Unknown keys in ``.env`` are rejected (``extra="forbid"``) so that a
    misspelled variable fails loudly instead of being silently ignored.

    Attributes:
        environment: Deployment environment. Controls error detail in
            responses and whether the refresh cookie is marked ``Secure``.
        database_url: SQLAlchemy URL for PostgreSQL through psycopg 3. It
            contains the database password, so it must never be logged.
        test_database_url: SQLAlchemy URL for the database the test suite
            uses. Unset outside development and CI; the test setup fails
            loudly when it is missing, so tests can never run against the
            development database by accident.
        jwt_secret_key: Key used to sign HS256 access tokens. At least 32
            characters, and different in every environment.
        access_token_expire_minutes: Lifetime of an access token in minutes.
        refresh_token_expire_days: Lifetime of a refresh token in days.
        hospital_timezone: IANA timezone name used for business rules such as
            "today" and appointment slot boundaries. Timestamps are still
            stored in UTC.
        cors_origins: Browser origins allowed to call the API. Empty in
            production, because the web app is served from the same origin.
        log_level: Minimum level of log records that are written.
        demo_mode: Whether demo accounts are protected from being
            deactivated or having their passwords changed.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    environment: Literal["local", "test", "production"] = "local"
    database_url: str
    test_database_url: str | None = None
    jwt_secret_key: SecretStr
    access_token_expire_minutes: Annotated[int, Field(gt=0)] = 15
    refresh_token_expire_days: Annotated[int, Field(gt=0)] = 7
    hospital_timezone: str = "Asia/Dubai"
    cors_origins: Annotated[list[str], NoDecode] = []
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    demo_mode: bool = False

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _check_database_url(cls, value: str | None) -> str | None:
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

        Returns:
            The unchanged URL.

        Raises:
            ValueError: If the URL does not start with
                ``postgresql+psycopg://``. The message never includes the URL,
                because it contains the password.
        """
        if value is None:
            return value
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must start with postgresql+psycopg://")
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
            ValueError: If the secret has fewer than 32 characters. The
                message never includes the secret itself.
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
        except (ZoneInfoNotFoundError, ValueError) as err:
            raise ValueError(f"HOSPITAL_TIMEZONE {value!r} is not a valid IANA timezone") from err
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: list[str] | str) -> list[str]:
        """Turn a comma-separated ``CORS_ORIGINS`` string into a list.

        Environment variables are plain strings, and a comma-separated list
        is easier to write than JSON. This runs before type validation, so it
        receives the raw value. Spaces around each origin are removed and
        empty items are dropped, so an empty variable gives an empty list.

        Args:
            value: A string such as ``"http://a.com, http://b.com"`` from the
                environment, or a list when settings are built directly in
                code, for example in tests.

        Returns:
            The list of origins. A list input is returned unchanged.

        Example:
            ``CORS_ORIGINS=" http://a.com , http://b.com,, "`` becomes
            ``["http://a.com", "http://b.com"]``.
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        """Whether the app is running in production.

        This is derived from ``environment`` rather than stored separately,
        so the two can never disagree, and it is not read from an environment
        variable. Security-sensitive code, such as the refresh cookie's
        ``Secure`` flag and the error handler's detail level, checks it.

        Returns:
            ``True`` only when ``environment`` is ``"production"``.
        """
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Build the settings once and return the same instance afterward.

    Settings are created on the first call instead of at import time, so
    importing a module never fails just because ``.env`` is missing. The
    cache makes every later call cheap and consistent. Tests that need
    different values can call ``get_settings.cache_clear()`` after changing
    the environment.

    Returns:
        The validated application settings.

    Raises:
        pydantic.ValidationError: If a required variable is missing or any
            value fails validation.

    Example:
        ``database_url = get_settings().database_url``
    """
    return Settings()  # type: ignore[call-arg]
