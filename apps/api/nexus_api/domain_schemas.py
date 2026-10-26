from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArtifactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["attack", "defence"]
    content: str = Field(min_length=1, max_length=16384)

    @field_validator("name")
    @classmethod
    def artifact_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Artifact name is required")
        return value.strip()


class ArtifactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    kind: str
    owner_id: UUID
    created_at: datetime
    sealed_at: datetime | None
    content_restricted: bool = False


class PrivateContentResponse(BaseModel):
    id: UUID
    content: str


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    status: str
    execution_mode: str
    evaluation_kind: Literal["legacy", "campaign"] = "legacy"
    sealed_at: datetime | None
    created_at: datetime


class ResultMetadata(BaseModel):
    total_requests: int | None = Field(default=None, ge=0, strict=True)
    allowed_count: int | None = Field(default=None, ge=0, strict=True)
    denied_count: int | None = Field(default=None, ge=0, strict=True)


class ResultResponse(BaseModel):
    evaluation_id: UUID
    summary: ResultMetadata
    verification_status: Literal["not_implemented"] = "not_implemented"


class PolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID
    name: str
    version: int
    content: dict
