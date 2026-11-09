"""The registry's Alembic environment.

The migration command hands Alembic the connection it opened, as the
``connection`` attribute of the Alembic configuration, so its adoption and
upgrade run on one connection. Run any other way, such as ``alembic revision``
during development, the environment opens its own from the database URL the
registry's settings name, read without any other setting
(:func:`core_registry.settings_source.load_database_settings`).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from core_registry.db.models import Base
from core_registry.settings_source import load_database_settings

config = context.config
target_metadata = Base.metadata

# Only the Alembic command line reads alembic.ini, and only it takes logging
# from there; the migration command has configured logging already.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or (
        load_database_settings().database_url
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
