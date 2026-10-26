"""Transactions own state changes, commitments and event sequence allocation."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from nexus_api.access import AccessError
from nexus_api.models import ArtifactVersion, Evaluation, SecurityEvent
from nexus_api.runtime_schemas import Budget, Corpus, GuardConfig
from nexus_api.versioning import POLICY, canonical, sha, verified_content

TRANSITIONS = {
    "CREATED": {"COMMITTED", "CANCELLED", "FAILED"},
    "COMMITTED": {"SEALED", "CANCELLED", "FAILED"},
    "SEALED": {"PROVISIONING", "CANCELLED", "FAILED"},
    "PROVISIONING": {"RUNNING", "FAILED", "CANCELLED"},
    "RUNNING": {"FINALIZING", "FAILED", "CANCELLED"},
    "FINALIZING": {"COMPLETED", "FAILED", "CANCELLED"},
    "COMPLETED": {"DESTROYED"},
    "FAILED": {"DESTROYED"},
    "CANCELLED": {"DESTROYED"},
    "DESTROYED": set(),
}


def locked(db, evaluation_id):
    return db.scalar(select(Evaluation).where(Evaluation.id == evaluation_id).with_for_update())


def emit(
    db,
    evaluation,
    event_type,
    *,
    source="API",
    destination="API",
    correlation=None,
    metadata=None,
    visibility="EVALUATION_METADATA",
    subject=None,
):
    # Caller holds the evaluation row lock. All runtime producers use this allocator.
    evaluation.event_sequence += 1
    event = SecurityEvent(
        evaluation_id=evaluation.id,
        sequence=evaluation.event_sequence,
        event_type=event_type,
        severity="warning" if "DENIED" in event_type else "info",
        source=source,
        destination=destination,
        correlation_id=correlation or uuid4(),
        visibility=visibility,
        subject_user_id=subject,
        event_metadata=metadata or {},
    )
    db.add(event)
    db.flush()
    return event


def transition(db, evaluation, target):
    if target not in TRANSITIONS.get(evaluation.status, set()):
        raise AccessError(409, "invalid_transition", "Evaluation state does not permit this action")
    evaluation.status = target
    if target == "SEALED":
        evaluation.sealed_at = datetime.now(UTC)
    if target == "RUNNING":
        evaluation.started_at = datetime.now(UTC)
    if target in {"COMPLETED", "FAILED", "CANCELLED", "DESTROYED"}:
        evaluation.finished_at = datetime.now(UTC)
    events = {
        "COMMITTED": "ARTIFACT_COMMITTED",
        "SEALED": "EVALUATION_SEALED",
        "PROVISIONING": "WORKLOAD_STARTING",
        "RUNNING": "WORKLOAD_READY",
        "FINALIZING": "EVALUATION_FINALIZING",
        "COMPLETED": "EVALUATION_COMPLETED",
        "FAILED": "EVALUATION_FAILED",
        "CANCELLED": "EVALUATION_CANCELLED",
        "DESTROYED": "WORKLOAD_DESTROYED",
    }
    emit(
        db,
        evaluation,
        events[target],
        metadata={"status": target, "execution_mode": evaluation.execution_mode},
    )


def bindings(db, evaluation):
    return [
        db.get(ArtifactVersion, getattr(evaluation, field))
        for field in (
            "red_version_id",
            "blue_version_id",
            "model_version_id",
            "flow_policy_version_id",
        )
    ]


def verify_evaluation(db, evaluation):
    records = bindings(db, evaluation)
    contents = [verified_content(record) for record in records]
    if (
        not evaluation.manifest
        or evaluation.manifest.get("execution_mode") != evaluation.execution_mode
        or sha(canonical(evaluation.manifest)) != evaluation.manifest_digest
        or [r.sha256 for r in records] != [v["sha256"] for v in evaluation.manifest["versions"]]
        or [str(r.id) for r in records]
        != [v["version_id"] for v in evaluation.manifest["versions"]]
        or contents[3] != POLICY
        or records[0].owner_id != evaluation.owner_id
        or [r.kind for r in records] != ["attack", "defence", "model", "flow_policy"]
    ):
        raise ValueError("MANIFEST_MISMATCH")
    if "campaign" in evaluation.manifest:
        from nexus_api.campaign_integrity import verify_campaign

        verify_campaign(db, evaluation, contents)
    else:
        Corpus.model_validate(contents[0])
        GuardConfig.model_validate(contents[1])
        Budget.model_validate(evaluation.manifest["budget"])
    return contents
