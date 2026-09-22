"""Alembic migration environment for the HMS database.

Alembic runs this file for every migration command. It takes the database
URL from the application settings, so no credentials live in alembic.ini,
and it compares the database with Base.metadata so that autogenerate and
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

# Cached application settings; supplies the database URL.
from app.core.config import get_settings

# Declarative base whose metadata lists every table for autogenerate.
from app.db.base import Base

# Alembic config object, giving access to the values in alembic.ini.
config = context.config

settings = get_settings()
# configparser treats "%" as special, so escape it in case the password contains one.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

# Set up loggers from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tables appear in Base.metadata only after their models module is imported,
# so every new models module must be imported in this file.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

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
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
