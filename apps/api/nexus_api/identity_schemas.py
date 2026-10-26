from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Role(StrEnum):
    RED = "RED_OPERATOR"
    BLUE = "BLUE_OPERATOR"
    AUDITOR = "AUDITOR"
    ADMIN = "ADMIN"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    display_name: str
    role: Role
    is_active: bool
    is_demo: bool


class CsrfResponse(BaseModel):
    csrf_token: str


class SessionResponse(CsrfResponse):
    user: UserResponse
    expires_at: datetime


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address")
        return value


class UserCreate(LoginRequest):
    display_name: str = Field(min_length=1, max_length=120)
    role: Role

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 12:
            raise ValueError("Passwords must contain at least 12 characters")
        return value


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role | None = None
    is_active: bool | None = None


class DemoIdentity(BaseModel):
    email: str
    display_name: str
    role: Role


class DemoConfigResponse(BaseModel):
    enabled: bool
    identities: list[DemoIdentity]
