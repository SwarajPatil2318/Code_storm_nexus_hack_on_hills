from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: SecretStr | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    provisioner_socket: str | None = None
    provisioner_key: SecretStr | None = None

    # Public trust metadata only; never a private key or signer database URL.
    proof_trusted_keys: dict[str, dict[str, str | None]] = {}

    # Trusted operator-configured directory; never supplied by a tenant request.
    assurance_catalog_dir: str | None = None

    demo_auth_enabled: bool = False
    cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=28800, ge=60, le=86400)
    login_attempt_limit: int = Field(default=8, ge=2, le=100)
    login_peer_limit: int = Field(default=120, ge=5, le=10000)
    login_window_seconds: int = Field(default=300, ge=10, le=3600)

    @model_validator(mode="after")
    def production_auth_safety(self):
        if self.environment == "production":
            if self.demo_auth_enabled:
                raise ValueError("Demo authentication is forbidden in production")
            if not self.cookie_secure:
                raise ValueError("Production requires secure authentication cookies")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production requires explicit HTTPS application origins")
            if not self.cors_origins:
                raise ValueError("Production requires an explicit application origin")
            if self.database_url:
                from sqlalchemy.engine import make_url

                url = make_url(self.database_url.get_secret_value())
                if not url.password or url.password in {
                    "nexus_local_only",
                    "changeme",
                    "password",
                    "replace-me",
                }:
                    raise ValueError(
                        "Production database credentials must be explicitly provisioned"
                    )
            if self.provisioner_key and (
                len(self.provisioner_key.get_secret_value()) != 64
                or len(set(self.provisioner_key.get_secret_value())) < 8
            ):
                raise ValueError("Production requires a provisioned runtime control key")
        return self

    @property
    def session_cookie_name(self) -> str:
        return "__Host-nexus_session" if self.cookie_secure else "nexus_session"

    @field_validator("provisioner_key")
    @classmethod
    def control_key_format(cls, value):
        if value:
            import re

            if not re.fullmatch(r"[a-f0-9]{64}", value.get_secret_value()):
                raise ValueError("Runtime control key must be a provisioned 32-byte hex key")
        return value

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr | None) -> SecretStr | None:
        if value and not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("Use a postgresql+psycopg database URL")
        return value

    @field_validator("cors_origins")
    @classmethod
    def explicit_origins(cls, origins: list[str]) -> list[str]:
        from urllib.parse import urlsplit

        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
                or parsed.username
                or parsed.password
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without a path")
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
