from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from backend.models import Base
from migrations.runtime import MigrationConfigurationError, get_migration_target


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configuration_options() -> dict[str, object]:
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
        "transactional_ddl": True,
        "include_schemas": False,
    }


def run_migrations_offline() -> None:
    target = get_migration_target()
    context.configure(
        url=target.url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configuration_options(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    target = get_migration_target()
    try:
        connectable = create_engine(target.url, poolclass=NullPool, hide_parameters=True, future=True)
        with connectable.connect() as connection:
            context.configure(connection=connection, **_configuration_options())
            with context.begin_transaction():
                context.run_migrations()
    except MigrationConfigurationError:
        raise
    except SQLAlchemyError:
        raise MigrationConfigurationError(
            f"Migration database connection or execution failed for {target.redacted_url}."
        ) from None
    finally:
        if "connectable" in locals():
            connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
