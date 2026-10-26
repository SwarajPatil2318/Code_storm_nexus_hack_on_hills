"""Versioned, allowlisted event envelopes shared by real application data and UI fixtures."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class EventType(StrEnum):
    EXECUTION_PROFILE_SELECTED = "EXECUTION_PROFILE_SELECTED"
    CPU_RESERVATION_REQUESTED = "CPU_RESERVATION_REQUESTED"
    CPU_ALLOCATION_GRANTED = "CPU_ALLOCATION_GRANTED"
    CPU_AFFINITY_VERIFIED = "CPU_AFFINITY_VERIFIED"
    CPU_ALLOCATION_RELEASED = "CPU_ALLOCATION_RELEASED"
    CPU_ALLOCATION_FAILED = "CPU_ALLOCATION_FAILED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    EVALUATION_RECONCILED = "EVALUATION_RECONCILED"
    RUNTIME_FOUND = "RUNTIME_FOUND"
    RUNTIME_MISSING = "RUNTIME_MISSING"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    CLEANUP_ATTEMPTED = "CLEANUP_ATTEMPTED"
    CLEANUP_VERIFIED = "CLEANUP_VERIFIED"
    CREDENTIALS_REVOKED = "CREDENTIALS_REVOKED"
    EVALUATION_INTERRUPTED = "EVALUATION_INTERRUPTED"
    MODEL_LOADING = "MODEL_LOADING"
    MODEL_READY = "MODEL_READY"
    ATTACK_CASE_STARTED = "ATTACK_CASE_STARTED"
    INPUT_GUARD_EVALUATED = "INPUT_GUARD_EVALUATED"
    MODEL_INFERENCE_STARTED = "MODEL_INFERENCE_STARTED"
    MODEL_INFERENCE_COMPLETED = "MODEL_INFERENCE_COMPLETED"
    OUTPUT_GUARD_EVALUATED = "OUTPUT_GUARD_EVALUATED"
    ATTACK_CASE_SCORED = "ATTACK_CASE_SCORED"
    ATTACK_CASE_FAILED = "ATTACK_CASE_FAILED"
    EVALUATION_PROGRESS = "EVALUATION_PROGRESS"
    MODEL_WORKER_STOPPED = "MODEL_WORKER_STOPPED"
    RUNTIME_UPDATED = "RUNTIME_UPDATED"
    RUNTIME_TEARDOWN = "RUNTIME_TEARDOWN"
    SECURITY_PROBE_RESULT = "SECURITY_PROBE_RESULT"
    EVALUATION_CREATED = "EVALUATION_CREATED"
    ARTIFACT_COMMITTED = "ARTIFACT_COMMITTED"
    EVALUATION_SEALED = "EVALUATION_SEALED"
    WORKLOAD_STARTING = "WORKLOAD_STARTING"
    WORKLOAD_READY = "WORKLOAD_READY"
    POLICY_ALLOWED = "POLICY_ALLOWED"
    POLICY_DENIED = "POLICY_DENIED"
    DEFENCE_INVOKED = "DEFENCE_INVOKED"
    MODEL_REQUESTED = "MODEL_REQUESTED"
    MODEL_RESPONDED = "MODEL_RESPONDED"
    RESULT_RELEASED = "RESULT_RELEASED"
    WORKLOAD_DESTROYED = "WORKLOAD_DESTROYED"
    SECURITY_PROBE_FAILED = "SECURITY_PROBE_FAILED"
    SECURITY_PROBE_PASSED = "SECURITY_PROBE_PASSED"
    EVIDENCE_SIGNED = "EVIDENCE_SIGNED"
    EVALUATION_FINALIZING = "EVALUATION_FINALIZING"
    EVALUATION_COMPLETED = "EVALUATION_COMPLETED"
    EVALUATION_FAILED = "EVALUATION_FAILED"
    EVALUATION_CANCELLED = "EVALUATION_CANCELLED"
    BLUE_APPROVED = "BLUE_APPROVED"
    AUTH_LOGIN_SUCCEEDED = "AUTH_LOGIN_SUCCEEDED"
    AUTH_LOGIN_FAILED = "AUTH_LOGIN_FAILED"
    AUTH_LOGOUT = "AUTH_LOGOUT"
    AUTH_THROTTLED = "AUTH_THROTTLED"
    AUTH_SESSION_EXPIRED = "AUTH_SESSION_EXPIRED"
    ACCESS_GRANTED = "ACCESS_GRANTED"
    ACCESS_DENIED = "ACCESS_DENIED"
    USER_UPDATED = "USER_UPDATED"
    USER_CREATED = "USER_CREATED"
    ARTIFACT_UPDATED = "ARTIFACT_UPDATED"
    ARTIFACT_DELETED = "ARTIFACT_DELETED"


class Visibility(StrEnum):
    EVALUATION = "EVALUATION_METADATA"
    RED = "RED_CONFIDENTIAL"
    BLUE = "BLUE_CONFIDENTIAL"
    AUDITOR = "AUDITOR_APPROVED"
    OPERATOR = "OPERATOR_PRIVATE"
    OPERATIONAL = "ADMIN_OPERATIONAL"


class EventSource(StrEnum):
    RED_OPERATOR = "RED_OPERATOR"
    BLUE_OPERATOR = "BLUE_OPERATOR"
    AUDITOR = "AUDITOR"
    ADMIN = "ADMIN"
    RED_RUNNER = "RED_RUNNER"
    REFERENCE_MONITOR = "REFERENCE_MONITOR"
    BLUE_INPUT_GUARD = "BLUE_INPUT_GUARD"
    BLUE_OUTPUT_GUARD = "BLUE_OUTPUT_GUARD"
    MODEL_WORKER = "MODEL_WORKER"
    BLUE_DEFENCE = "BLUE_DEFENCE"
    CLIENT_LLM = "CLIENT_LLM"
    EVIDENCE_COLLECTOR = "EVIDENCE_COLLECTOR"
    PROVISIONER = "PROVISIONER"
    API = "API"
    IDENTITY_SERVICE = "IDENTITY_SERVICE"


class PermittedMetadata(BaseModel):
    # Unknown keys and malformed values are dropped by the serializer, never streamed.
    model_config = ConfigDict(extra="forbid")
    security_profile: Literal["STANDARD", "REDUCED_INTERFERENCE"] | None = None
    affinity_status: Literal["PENDING", "VERIFIED", "FAILED", "RELEASED"] | None = None
    allocation_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    queue_wait_ms: int | None = Field(default=None, ge=0, le=60000)
    provider: Literal["mock", "local"] | None = None
    case_index: int | None = Field(default=None, ge=0, le=39, strict=True)
    defence_action: Literal["ALLOW", "TRANSFORM", "BLOCK"] | None = None
    model_execution: Literal["EXECUTED", "SKIPPED", "ERROR", "TIMEOUT"] | None = None
    attack_outcome: Literal["SUCCESS", "FAILURE", "INCONCLUSIVE", "NOT_EVALUATED"] | None = None
    prompt_tokens: int | None = Field(default=None, ge=0, le=2048, strict=True)
    completion_tokens: int | None = Field(default=None, ge=0, le=128, strict=True)
    completed_cases: int | None = Field(default=None, ge=0, le=40, strict=True)
    total_cases: int | None = Field(default=None, ge=1, le=40, strict=True)
    decision: str | None = Field(default=None, pattern="^(ALLOW|DENY)$")
    reason_code: str | None = Field(default=None, pattern="^[A-Z0-9_]{1,64}$")
    artifact_id: UUID | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=86400000, strict=True)
    verification_status: str | None = Field(default=None, pattern="^(pending|verified|failed)$")
    status: str | None = Field(
        default=None,
        pattern="^(planned|draft|queued|ready|failed|completed|CREATED|COMMITTED|SEALED|PROVISIONING|RUNNING|FINALIZING|COMPLETED|DESTROYED|FAILED|CANCELLED)$",
    )
    policy_digest: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    policy_version: Literal["local-flow-v1"] | None = None
    message_type: str | None = Field(default=None, pattern="^[A-Z_]{1,40}$")
    execution_mode: Literal["local_mock", "isolated_docker"] | None = None
    guard_stage: Literal["input", "output"] | None = None
    runtime_state: (
        Literal["PROVISIONING", "READY", "PROBING", "TEARDOWN", "CLEANED", "CLEANUP_FAILED"] | None
    ) = None
    workload_count: int | None = Field(default=None, ge=0, le=3, strict=True)
    cleanup_status: Literal["PENDING", "VERIFIED", "FAILED"] | None = None
    probe_id: str | None = Field(default=None, pattern="^[A-Z_]{1,64}$")
    probe_status: Literal["PASS", "FAIL", "UNSUPPORTED", "INCONCLUSIVE"] | None = None
    cpu_percent: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    memory_bytes: int | None = Field(default=None, ge=0, le=2147483648, strict=True)
    object_kind: str | None = Field(default=None, pattern="^(attack|defence|policy|user|session)$")


class SecurityEventResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    sequence: int | None = Field(default=None, ge=1)
    event_id: UUID
    evaluation_id: UUID | None
    event_type: EventType
    timestamp: datetime
    source: EventSource
    destination: EventSource
    visibility: Visibility
    permitted_metadata: PermittedMetadata
    correlation_id: UUID
    origin: Literal["APPLICATION", "RUNTIME", "SIMULATED"]


def sanitize_metadata(raw: dict) -> PermittedMetadata:
    clean = {}
    for key, value in raw.items():
        if key not in PermittedMetadata.model_fields:
            continue
        try:
            field = PermittedMetadata.model_validate({key: value})
            clean.update(field.model_dump(exclude_none=True))
        except ValidationError:
            continue
    return PermittedMetadata.model_validate(clean)
