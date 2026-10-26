from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase

from nexus_api.config import Settings

SCHEMA_REVISION = "0008_proof_vault"


class Base(DeclarativeBase):
    pass


def make_engine(settings: Settings) -> Engine | None:
    if settings.database_url is None:
        return None
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=3,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
        hide_parameters=True,
    )
