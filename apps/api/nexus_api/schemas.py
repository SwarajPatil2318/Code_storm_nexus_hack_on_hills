from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["nexus-api"] = "nexus-api"
    version: str = "0.1.0"
    mode: Literal["foundation"] = "foundation"


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal[
        "connected", "unconfigured", "unavailable", "migration_required", "unsafe_privileges"
    ]


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class EvaluationDraft(BaseModel):
    """Future request contract. No public creation route exists in Milestone 1."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    policy_id: UUID | None = None
    execution_mode: Literal["mock", "production"]
