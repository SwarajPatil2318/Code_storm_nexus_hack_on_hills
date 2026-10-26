from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, pool

from alembic import context
from nexus_api import models  # noqa: F401
from nexus_api.database import Base


class MigrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    migration_database_url: SecretStr | None = None


settings = MigrationSettings()
provided_connection = context.config.attributes.get("connection")
if settings.migration_database_url is None and provided_connection is None:
    raise RuntimeError(
        "Set NEXUS_MIGRATION_DATABASE_URL; runtime credentials are never a migration fallback"
    )
url = (
    settings.migration_database_url.get_secret_value() if settings.migration_database_url else None
)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def configure_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    provided = context.config.attributes.get("connection")
    if provided is not None:
        configure_connection(provided)
        return
    connectable = create_engine(
        url, poolclass=pool.NullPool, hide_parameters=True, connect_args={"connect_timeout": 3}
    )
    with connectable.connect() as connection:
        configure_connection(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
