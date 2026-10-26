"""Strict local runtime contracts. No service identity is accepted from HTTP clients."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from nexus_api.campaign_schemas import AttackCorpus, BluePolicy
from nexus_api.schema_base import Strict


class Domain(StrEnum):
    RED = "RED_RUNNER"
    MONITOR = "REFERENCE_MONITOR"
    INPUT = "BLUE_INPUT_GUARD"
    MODEL = "MODEL_WORKER"
    OUTPUT = "BLUE_OUTPUT_GUARD"


class MessageType(StrEnum):
    ATTACK = "ATTACK_SUBMISSION"
    INPUT_REQUEST = "DEFENCE_INPUT_REQUEST"
    INPUT_RESULT = "DEFENCE_INPUT_RESULT"
    MODEL_REQUEST = "MODEL_INFERENCE_REQUEST"
    MODEL_RESULT = "MODEL_INFERENCE_RESULT"
    OUTPUT_REQUEST = "DEFENCE_OUTPUT_REQUEST"
    OUTPUT_RESULT = "DEFENCE_OUTPUT_RESULT"
    FINAL = "FINAL_RESULT"


class TextPayload(Strict):
    kind: Literal["text"]
    text: str = Field(max_length=4096)


class GuardPayload(Strict):
    kind: Literal["guard"]
    approved: bool = Field(strict=True)
    text: str = Field(max_length=4096)


class ReleasePayload(Strict):
    kind: Literal["release"]
    outcome: Literal["released", "withheld"]
    response: Literal["Mock response: request handled.", "Response withheld."]

    @model_validator(mode="after")
    def release_pair(self):
        if (self.outcome == "released") != (self.response == "Mock response: request handled."):
            raise ValueError("Invalid release projection")
        return self


class CampaignReleasePayload(Strict):
    kind: Literal["campaign_release"]
    outcome: Literal["released", "withheld"]
    response: str = Field(max_length=4096)

    @model_validator(mode="after")
    def withheld_is_constant(self):
        if self.outcome == "withheld" and self.response != "Response withheld.":
            raise ValueError("Withheld output must not disclose content")
        return self


class MessageMetadata(Strict):
    adapter_version: Literal["local-v1", "campaign-v1"] = "local-v1"


class Envelope(Strict):
    message_id: UUID
    evaluation_id: UUID
    correlation_id: UUID
    source_domain: Domain
    destination_domain: Domain
    message_type: MessageType
    schema_version: Literal["1.0"] = "1.0"
    timestamp: datetime
    payload: Annotated[
        TextPayload | GuardPayload | ReleasePayload | CampaignReleasePayload,
        Field(discriminator="kind"),
    ]
    metadata: MessageMetadata = MessageMetadata()

    @model_validator(mode="after")
    def matching_payload(self):
        expected = (
            ("campaign_release" if self.metadata.adapter_version == "campaign-v1" else "release")
            if self.message_type == MessageType.FINAL
            else (
                "guard"
                if self.message_type in {MessageType.INPUT_RESULT, MessageType.OUTPUT_RESULT}
                else "text"
            )
        )
        if self.payload.kind != expected or self.timestamp.tzinfo is None:
            raise ValueError("Invalid payload type or timestamp")
        return self


class Case(Strict):
    prompt: str = Field(min_length=1, max_length=2048)
    route: Literal["mediated", "direct_blue", "direct_model"] = "mediated"


class Corpus(Strict):
    cases: list[Case] = Field(min_length=1, max_length=20)


class GuardConfig(Strict):
    blocked_terms: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=lambda: ["CANARY_PRIVATE"], max_length=20
    )
    block_input: bool = Field(default=False, strict=True)


class Budget(Strict):
    model_timeout_ms: int = Field(default=200, ge=20, le=1000, strict=True)
    max_cases: int = Field(default=5, ge=1, le=20, strict=True)
    max_messages: int = Field(default=160, ge=1, le=160, strict=True)
    max_bytes: int = Field(default=8192, ge=512, le=8192, strict=True)
    timeout_seconds: int = Field(default=10, ge=1, le=30, strict=True)


class EvaluationCreate(Strict):
    execution_mode: Literal["local_mock", "isolated_docker"] = "local_mock"
    name: str = Field(min_length=1, max_length=160)
    red_version_id: UUID
    blue_version_id: UUID
    policy_version: Literal["local-flow-v1"] = "local-flow-v1"
    model_mode: Literal["safe", "canary", "error", "timeout"] = "safe"
    budget: Budget = Budget()


class VersionCreate(Strict):
    content: Corpus | GuardConfig | AttackCorpus | BluePolicy


class VersionResponse(Strict):
    version_id: UUID
    artifact_id: UUID | None
    owner_id: UUID
    domain: str
    kind: str
    sha256: str
    byte_size: int
    content_ref: str
    created_at: datetime
    visibility: str


class GrantCreate(Strict):
    red_email: str = Field(min_length=3, max_length=320)


class GrantResponse(Strict):
    version_id: UUID
    red_id: UUID


class ManifestResponse(Strict):
    evaluation_id: UUID
    status: str
    execution_mode: Literal["local_mock", "isolated_docker"]
    manifest_digest: str | None
    manifest: dict  # Safe fixed projection constructed on server; never internal content.
    blue_approved: bool


class ReleasedResult(Strict):
    evaluation_id: UUID
    results: list[ReleasePayload]
    model: Literal["MOCK_NOT_SAFETY_EVIDENCE"] = "MOCK_NOT_SAFETY_EVIDENCE"


class PolicyDecision(Strict):
    evaluation_id: UUID
    correlation_id: UUID
    source_domain: str
    destination_domain: str
    message_type: str
    decision: Literal["ALLOW", "DENY"]
    reason_code: str
    policy_version: Literal["local-flow-v1"] = "local-flow-v1"
    policy_digest: str
    timestamp: datetime


class AuditorCreate(Strict):
    email: str = Field(min_length=3, max_length=320)
