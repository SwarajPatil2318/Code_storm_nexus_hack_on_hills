"""Independent outcome, provenance, integrity and completeness dimensions."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from nexus_api.assurance_schemas import AssuranceReport
from nexus_api.events import PermittedMetadata
from nexus_api.proof_format import Verification
from nexus_api.resource_schemas import ResourceReport
from nexus_api.runtime_dto import IsolationView
from nexus_api.schema_base import Strict
from nexus_api.timing_schemas import TimingReport

Outcome = Literal["PASS", "FAIL", "PARTIAL", "INCONCLUSIVE", "UNSUPPORTED", "NOT_TESTED"]
ObjectiveId = Literal["functional", "confidentiality", "audit", "deployment", "llm", "resources"]


class ArchiveGrant(Strict):
    local_subject: UUID
    role: Literal["RED_OPERATOR", "BLUE_OPERATOR", "AUDITOR"]
    original_subject: UUID


class ArchiveEntry(Strict):
    id: UUID
    environment: Literal["M8", "M9", "M10", "M10.1"]
    evaluation_id: UUID
    snapshot_id: UUID
    bundle_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    report_kind: Literal["runtime", "assurance_report", "resource_report", "timing_report"]
    grants: list[ArchiveGrant] = Field(min_length=1, max_length=8)


class ArchiveCatalog(Strict):
    schema_version: Literal["assurance-catalog-v1"] = "assurance-catalog-v1"
    entries: list[ArchiveEntry] = Field(max_length=16)
    trusted_keys: dict[str, dict[str, str | None]] = Field(default_factory=dict, max_length=16)


class CenterVersion(Strict):
    kind: str
    version_id: UUID
    sha256: str
    byte_size: int


class CenterSource(Strict):
    id: str
    environment: str
    evaluation_id: UUID
    snapshot_id: UUID | None = None
    signed_at: str | None = None
    original_subject: UUID | None = None
    profile: str
    bundle_sha256: str | None = None
    receipt_digest: str | None = None
    methodology: str | None = None
    verification: Verification | None = None
    condition: Literal[
        "AVAILABLE",
        "MISSING",
        "INVALID",
        "UNTRUSTED",
        "INCOMPLETE",
        "STALE",
        "UNSIGNED",
        "NOT_VERIFIED",
    ]
    coverage: str
    provenance: Literal["RECORDED_APPLICATION", "OPERATOR_EXPERIMENT_ATTESTATION"]
    export_url: str | None = None
    proof_url: str | None = None
    trace_url: str | None = None
    snapshot_commitment: str | None = None
    versions: list[CenterVersion] = Field(default_factory=list)


class CenterFinding(Strict):
    id: str
    objective: ObjectiveId
    title: str
    outcome: Outcome
    source_id: str | None = None
    detail: str
    measurements: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=30
    )
    limitations: list[str] = Field(default_factory=list, max_length=12)
    provenance: Literal["RECORDED_APPLICATION", "OPERATOR_EXPERIMENT_ATTESTATION", "UNPROVEN"]


class ArchivedExperiment(Strict):
    source: CenterSource
    isolation: IsolationView | None = None
    assurance_report: AssuranceReport | None = None
    resource_report: ResourceReport | None = None
    timing_report: TimingReport | None = None
    related_sources: list[CenterSource] = Field(default_factory=list, max_length=16)


class CenterObjective(Strict):
    id: ObjectiveId
    title: str
    outcome: Outcome
    outcomes: dict[str, int]
    findings: list[CenterFinding]


class CenterView(Strict):
    schema_version: Literal["assurance-center-v1"] = "assurance-center-v1"
    sources: list[CenterSource]
    objectives: list[CenterObjective]
    unresolved_risk: str
    catalog_condition: Literal["AVAILABLE", "NOT_CONFIGURED", "UNAVAILABLE"]


class CenterEvaluation(Strict):
    id: UUID
    name: str
    state: str


class ArchiveEvent(Strict):
    sequence: int
    source_sequence: int
    event_type: str
    timestamp: str
    event_id: UUID
    metadata: PermittedMetadata


class ArchiveHistory(Strict):
    evaluation_id: UUID
    snapshot_id: UUID
    events: list[ArchiveEvent]
    next_after: int
    has_more: bool
    recorded_events: int
    source_watermark: int
    coverage: str
