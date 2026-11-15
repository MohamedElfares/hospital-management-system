"""Alembic migration environment for the HMS database.

Alembic runs this file for every command that works on the database:
``upgrade``, ``downgrade``, ``current``, ``check``, and
``revision --autogenerate`` connect to it, and ``upgrade --sql`` prints the
SQL instead. Commands that only read the migration files, such as
``history`` and ``heads``, don't run it. It takes the database URL from the
application settings, so no credentials live in alembic.ini, and it
compares the database with Base.metadata so that autogenerate and
``alembic check`` see every model.
"""

# Configures Python logging from the [loggers] sections of alembic.ini.
from logging.config import fileConfig

# Alembic's runtime context: the config object and the migration runner.
from alembic import context

# Builds an engine from the sqlalchemy.* options in the Alembic config.
from sqlalchemy import engine_from_config

# Connection pool classes; NullPool opens one connection for the command.
from sqlalchemy import pool

# Registers the refresh_tokens table in Base.metadata so autogenerate can see it.
import app.modules.auth.models

# Registers the users table in Base.metadata so autogenerate can see it.
import app.modules.users.models  # noqa: F401

# Cached application settings; supplies the database URL.
from app.core.config import get_settings

# Declarative base whose metadata lists every table for autogenerate.
from app.db.base import Base

# Alembic config object, giving access to the values in alembic.ini.
config = context.config

settings = get_settings()
# configparser treats "%" as special, so escape it in case the password contains one.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

# alembic.ini's [loggers] sections make Alembic print each migration it runs;
# a Config built in Python has no file to read.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tables appear in Base.metadata only after their models module is imported,
# so every new models module must be imported in this file.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Print the migration SQL instead of running it.

    ``alembic upgrade head --sql`` uses this mode. Alembic needs only the
    URL, to choose the SQL dialect, so no connection is opened, and
    ``literal_binds`` writes values into the SQL instead of placeholders.
    Use it to review a migration's SQL before applying it to production.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and run the command against it.

    ``NullPool`` closes the connection when the command ends instead of
    keeping it in a pool, because the process exits right after. On
    PostgreSQL all the migrations one command runs share a transaction, so
    if one fails, none of them is applied.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # Fail within seconds when the database is unreachable, like the app's
        # engine, instead of waiting for the operating system's TCP timeout.
        connect_args={"connect_timeout": 5},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Alembic skips server defaults unless asked, so a changed default,
            # such as must_change_password's, would pass alembic check.
            compare_server_default=True,
            # Alembic's default plugins skip CHECK constraints. This opt-in one
            # compares them by name: it catches one added or removed without a
            # migration, but not a changed rule, such as a new enum value.
            autogenerate_plugins=["alembic.autogenerate.*", "alembic.ext.checkconstraint_byname"],
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
