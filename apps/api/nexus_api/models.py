"""Initial persistence schema; domain access is deliberately not exposed over HTTP."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from nexus_api.database import Base


class IdentityMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(IdentityMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('RED_OPERATOR', 'BLUE_OPERATOR', 'AUDITOR', 'ADMIN')", name="user_role"
        ),
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Policy(IdentityMixin, Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", "version", name="uq_policy_version"),
        CheckConstraint("version > 0", name="policy_version_positive"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Sensitive policy content must remain Blue-only in subsequent authorized services.
    content: Mapped[dict] = mapped_column(JSONB, default=dict)


class Artifact(IdentityMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("kind IN ('defence', 'attack', 'evidence')", name="artifact_kind"),
        CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="artifact_sha256"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("policies.id"))
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    storage_key: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    private_content: Mapped[str | None] = mapped_column(Text)


class Evaluation(IdentityMixin, Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED','COMMITTED','SEALED','PROVISIONING','RUNNING','FINALIZING',"
            "'COMPLETED','DESTROYED','FAILED','CANCELLED')",
            name="evaluation_status",
        ),
        CheckConstraint(
            "execution_mode IN ('mock', 'production', 'local_mock', 'isolated_docker')",
            name="execution_mode",
        ),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("policies.id"))
    defence_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="CREATED")
    # Required explicitly; mock and production must never be conflated.
    execution_mode: Mapped[str] = mapped_column(String(16))
    red_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifact_versions.id"))
    blue_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifact_versions.id"))
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifact_versions.id"))
    flow_policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifact_versions.id")
    )
    manifest: Mapped[dict | None] = mapped_column(JSONB)
    manifest_digest: Mapped[str | None] = mapped_column(String(64))
    blue_approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    worker_claimed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    proof_native: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    event_sequence: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def evaluation_kind(self):
        return "campaign" if self.manifest and "campaign" in self.manifest else "legacy"


class SecurityEvent(IdentityMixin, Base):
    __tablename__ = "security_events"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "sequence", name="uq_event_sequence"),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="event_severity"),
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    sequence: Mapped[int | None] = mapped_column(BigInteger)
    severity: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(40), default="API", server_default="API")
    destination: Mapped[str] = mapped_column(String(40), default="API", server_default="API")
    visibility: Mapped[str] = mapped_column(
        String(40), default="EVALUATION_METADATA", server_default="EVALUATION_METADATA"
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_security_events_subject_user_id")
    )
    # Serializers permit only typed metadata fields; private payloads are never streamed.
    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)


class EvaluationResult(IdentityMixin, Base):
    __tablename__ = "evaluation_results"
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"), unique=True)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))


class AuthSession(IdentityMixin, Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginThrottle(Base):
    __tablename__ = "login_throttles"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthAudit(IdentityMixin, Base):
    __tablename__ = "auth_audit"
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    correlation_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)
    reason_code: Mapped[str] = mapped_column(String(64))


class EvaluationMembership(Base):
    __tablename__ = "evaluation_memberships"
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class ArtifactVersion(IdentityMixin, Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        CheckConstraint("kind IN ('attack','defence','model','flow_policy')", name="version_kind"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="version_sha"),
        CheckConstraint("byte_size > 0 AND byte_size <= 65536", name="version_size"),
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    domain: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(24))
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(40))
    content_ref: Mapped[str] = mapped_column(String(80), unique=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class VersionGrant(Base):
    __tablename__ = "version_grants"
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact_versions.id"), primary_key=True
    )
    red_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class RuntimeRecord(Base):
    __tablename__ = "runtime_records"
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"), primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvaluationJob(Base):
    """Durable intent, ownership and cleanup observations; never a resumption queue."""

    __tablename__ = "evaluation_jobs"
    __table_args__ = (
        CheckConstraint("operation IN ('run','probes','destroy')", name="job_operation"),
        CheckConstraint("state IN ('PENDING','RUNNING','RECOVERING','FINISHED')", name="job_state"),
        CheckConstraint("cleanup IN ('PENDING','VERIFIED','FAILED')", name="job_cleanup"),
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"), primary_key=True)
    runtime_owner: Mapped[str | None] = mapped_column(String(36), index=True)
    operation: Mapped[str] = mapped_column(String(16), default="run")
    state: Mapped[str] = mapped_column(String(16), default="PENDING")
    claim_id: Mapped[uuid.UUID | None] = mapped_column()
    cleanup: Mapped[str] = mapped_column(String(16), default="PENDING")
    credentials_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comparison(IdentityMixin, Base):
    __tablename__ = "comparisons"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    baseline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"), unique=True)
    defended_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"), unique=True)
    manifest: Mapped[dict] = mapped_column(JSONB)
    manifest_digest: Mapped[str] = mapped_column(String(64))


class CaseRecord(IdentityMixin, Base):
    __tablename__ = "case_records"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "case_id", name="uq_case_identifier"),
        UniqueConstraint("evaluation_id", "case_index", name="uq_case_index"),
        CheckConstraint("case_index >= 0 AND case_index < 40", name="bounded_case_index"),
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"))
    case_id: Mapped[str] = mapped_column(String(40))
    case_index: Mapped[int] = mapped_column(Integer)
    correlation_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    result: Mapped[dict] = mapped_column(JSONB)
    private_guard: Mapped[dict] = mapped_column(JSONB)


class EvidenceSnapshot(IdentityMixin, Base):
    """Private frozen internal bundle. Public API has no SELECT privilege."""

    __tablename__ = "evidence_snapshots"
    __table_args__ = (UniqueConstraint("evaluation_id", "watermark", name="uq_proof_snapshot"),)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"))
    watermark: Mapped[int] = mapped_column(BigInteger)
    supersedes: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snapshots.id"))
    internal_bundle: Mapped[bytes] = mapped_column(LargeBinary)


class EvidenceReceipt(IdentityMixin, Base):
    __tablename__ = "evidence_receipts"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "subject_id", "profile", name="uq_proof_projection"),
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_snapshots.id"))
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"))
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    profile: Mapped[str] = mapped_column(String(24))
    watermark: Mapped[int] = mapped_column(BigInteger)
    envelope: Mapped[dict] = mapped_column(JSONB)
    bundle: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class EvidenceRequest(IdentityMixin, Base):
    __tablename__ = "evidence_requests"
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"))
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    retrospective: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(16), default="PENDING")
    reason_code: Mapped[str | None] = mapped_column(String(64))
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_receipts.id"))


class EvidenceVerification(IdentityMixin, Base):
    __tablename__ = "evidence_verifications"
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"))
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_receipts.id"))
    result: Mapped[dict] = mapped_column(JSONB)


class EvidenceKey(Base):
    __tablename__ = "evidence_keys"
    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    public_key: Mapped[str] = mapped_column(String(160))
    activated_at: Mapped[str] = mapped_column(String(27))
    retired_at: Mapped[str | None] = mapped_column(String(27))


class EvidenceExport(IdentityMixin, Base):
    __tablename__ = "evidence_exports"
    evaluation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluations.id"))
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_receipts.id"))
