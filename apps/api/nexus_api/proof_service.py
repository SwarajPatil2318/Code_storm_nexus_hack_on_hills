"""Trusted snapshot builder; only the separate restricted worker calls finalize."""

import os
import secrets
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from nexus_api.authorization import can_see_event, membership_clause, serialize_event
from nexus_api.campaign_results import summary
from nexus_api.lifecycle import bindings, locked, verify_evaluation
from nexus_api.models import (
    CaseRecord,
    Evaluation,
    EvaluationJob,
    EvaluationResult,
    EvidenceReceipt,
    EvidenceRequest,
    EvidenceSnapshot,
    RuntimeRecord,
    SecurityEvent,
    User,
)
from nexus_api.proof_format import (
    MAX_BUNDLE,
    MAX_EVENTS,
    b64,
    build_chain,
    digest,
    measured,
    parse,
    seal_bundle,
    unb64,
    verify,
)
from nexus_api.signing_claim import SigningClaim

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "DESTROYED"}
ROLES = {"RED_OPERATOR", "BLUE_OPERATOR", "AUDITOR"}


def timestamp(value=None):
    return (
        (value or datetime.now(UTC))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def member(db, user, eid):
    return (
        user is not None
        and user.is_active
        and user.role in ROLES
        and db.scalar(select(Evaluation.id).where(Evaluation.id == eid, membership_clause(user.id)))
        is not None
    )


def raw_event(row):
    projected = serialize_event(row)
    return {
        "event_id": str(row.id),
        "source_sequence": row.sequence,
        "event_type": row.event_type,
        "source": row.source,
        "destination": row.destination,
        "timestamp": timestamp(row.created_at),
        "correlation_id": str(row.correlation_id),
        "visibility": row.visibility,
        "payload": {
            "metadata": measured(row.event_metadata),
            "public": measured(
                projected.permitted_metadata.model_dump(mode="json", exclude_none=True)
            )
            if projected
            else None,
            "subject_user_id": str(row.subject_user_id) if row.subject_user_id else None,
        },
    }


def unpack(raw):
    bundle = parse(raw)
    return [parse(unb64(file["content"])) for file in bundle["files"]]


def cleanup_state(db, evaluation):
    job = db.get(EvaluationJob, evaluation.id)
    runtime = db.get(RuntimeRecord, evaluation.id)
    if evaluation.execution_mode == "isolated_docker":
        if runtime:
            return runtime.snapshot.get("cleanup", "PENDING")
        return "NOT_STARTED" if not evaluation.worker_claimed else "PENDING"
    if not evaluation.worker_claimed:
        return "NOT_STARTED"
    return "IN_PROCESS_ONLY" if job and job.state == "FINISHED" else "PENDING"


def make_snapshot(db, evaluation, key):
    verify_evaluation(db, evaluation)
    if not 1 <= evaluation.event_sequence <= MAX_EVENTS:
        raise ValueError("INCOMPLETE_EVENT_HISTORY")
    payload_bytes = (
        db.scalar(
            select(func.sum(func.pg_column_size(SecurityEvent.event_metadata))).where(
                SecurityEvent.evaluation_id == evaluation.id
            )
        )
        or 0
    )
    if payload_bytes > MAX_BUNDLE:
        raise ValueError("EVIDENCE_SIZE_LIMIT")
    records = list(
        db.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.evaluation_id == evaluation.id)
            .order_by(SecurityEvent.sequence)
            .limit(MAX_EVENTS + 1)
        )
    )
    if len(records) > MAX_EVENTS or [r.sequence for r in records] != list(
        range(1, evaluation.event_sequence + 1)
    ):
        raise ValueError("INCOMPLETE_EVENT_HISTORY")
    expected_terminal = {
        "COMPLETED": "EVALUATION_COMPLETED",
        "FAILED": "EVALUATION_FAILED",
        "CANCELLED": "EVALUATION_CANCELLED",
        "DESTROYED": "WORKLOAD_DESTROYED",
    }[evaluation.status]
    if expected_terminal not in {r.event_type for r in records}:
        raise ValueError("TERMINAL_EVENT_MISSING")
    sid = str(uuid4())
    eid = str(evaluation.id)
    frozen = timestamp()
    cleanup = cleanup_state(db, evaluation)
    prior = db.scalar(
        select(EvidenceSnapshot)
        .where(EvidenceSnapshot.evaluation_id == evaluation.id)
        .order_by(EvidenceSnapshot.watermark.desc())
        .limit(1)
    )
    artifacts = []
    for record in bindings(db, evaluation):
        opening = {
            "nonce": secrets.token_hex(32),
            "version_id": str(record.id),
            "kind": record.kind,
            "sha256": record.sha256,
            "byte_size": record.byte_size,
        }
        artifacts.append(
            {
                "kind": record.kind,
                "commitment": digest("artifact", opening),
                "opening": opening,
                "data": b64(record.data),
            }
        )
    stored = db.scalar(
        select(EvaluationResult).where(EvaluationResult.evaluation_id == evaluation.id)
    )
    if evaluation.status == "COMPLETED" and stored is None:
        raise ValueError("EXPECTED_RESULT_MISSING")
    cases = list(
        db.scalars(
            select(CaseRecord)
            .where(CaseRecord.evaluation_id == evaluation.id)
            .order_by(CaseRecord.case_index)
        )
    )
    runtime = db.get(RuntimeRecord, evaluation.id)
    results = {
        "evaluation_id": eid,
        "terminal_status": evaluation.status,
        "stored_result": stored.summary if stored else None,
        "private_cases": [{"result": r.result, "private_guard": r.private_guard} for r in cases],
        "red_projection": summary(db, evaluation, private=True).model_dump(mode="json")
        if evaluation.evaluation_kind == "campaign"
        else (stored.summary if stored else None),
        "metadata_projection": summary(db, evaluation, private=False).model_dump(mode="json")
        if evaluation.evaluation_kind == "campaign"
        else {"available": stored is not None},
        "runtime": runtime.snapshot if runtime else None,
    }
    results = measured(results)
    context = {
        "evaluation_id": eid,
        "snapshot_id": sid,
        "profile": "INTERNAL",
        "subject_id": None,
        "source_watermark": evaluation.event_sequence,
    }
    events, chain = build_chain([raw_event(r) for r in records], context)
    nonce = secrets.token_hex(32)
    commitment = digest(
        "internal",
        {
            "nonce": nonce,
            "configuration": evaluation.manifest,
            "events": events,
            "artifacts": artifacts,
            "results": results,
        },
    )
    manifest = {
        **context,
        "format": "nexus-manifest-v1",
        "frozen_at": frozen,
        "source_count": len(records),
        "chain": chain,
        "terminal_status": evaluation.status,
        "cleanup": cleanup,
        "retrospective": not evaluation.proof_native,
        "coverage": "FULL_INTERNAL_SNAPSHOT",
        "supersedes": str(prior.id) if prior else None,
        "internal_commitment": commitment,
        "configuration": {"opening": nonce, "committed_manifest": evaluation.manifest},
        "artifact_commitments": [a["commitment"] for a in artifacts],
        "disclosed_artifacts": [a["kind"] for a in artifacts],
        "limitations": [
            "Authenticates a recorded snapshot; event truth and host integrity remain trusted.",
            "Closed sequence prefix; later observations require a linked snapshot.",
        ],
    }
    raw = seal_bundle(manifest, events, artifacts, results, key)
    snapshot = EvidenceSnapshot(
        id=UUID(sid),
        evaluation_id=evaluation.id,
        watermark=evaluation.event_sequence,
        supersedes=prior.id if prior else None,
        internal_bundle=raw,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def project(db, evaluation, snapshot, user, key, keyring):
    if verify(snapshot.internal_bundle, keyring).status != "VALID":
        raise ValueError("INTERNAL_RECEIPT_UNTRUSTED")
    manifest, internal_events, artifacts, internal_results = unpack(snapshot.internal_bundle)
    profile = user.role
    selected = []
    for event in internal_events:
        payload = event["payload"]
        subject = payload["subject_user_id"]
        if payload["public"] is None or not can_see_event(
            user,
            SimpleNamespace(
                visibility=event["visibility"], subject_user_id=UUID(subject) if subject else None
            ),
            evaluation,
        ):
            continue
        selected.append(
            {
                k: event[k]
                for k in [
                    "event_id",
                    "source_sequence",
                    "event_type",
                    "source",
                    "destination",
                    "timestamp",
                    "correlation_id",
                    "visibility",
                ]
            }
            | {"payload": payload["public"]}
        )
    context = {k: manifest[k] for k in ["evaluation_id", "snapshot_id", "source_watermark"]}
    context.update(profile=profile, subject_id=str(user.id))
    events, chain = build_chain(selected, context)
    filtered = []
    owners = {str(v.id): v.owner_id for v in bindings(db, evaluation)}
    for a in artifacts:
        own = (a["kind"] == "attack" and profile == "RED_OPERATOR") or (
            a["kind"] == "defence" and profile == "BLUE_OPERATOR"
        )
        visible = a["kind"] in {"model", "flow_policy"} or (
            own and owners.get(a["opening"]["version_id"]) == user.id
        )
        filtered.append(a if visible else {**a, "opening": None, "data": None})
    committed = manifest["configuration"]["committed_manifest"]
    config = {
        k: committed[k]
        for k in [
            "schema_version",
            "execution_mode",
            "security_profile",
            "budget",
            "model",
            "campaign",
            "runtime_images",
        ]
        if k in committed
    }
    # No confidential version digests, private opening nonces, case text or guard internals.
    visible_kinds = [a["kind"] for a in filtered if a["opening"] is not None]
    config["visible_version_bindings"] = [
        v for v in committed["versions"] if v["kind"] in visible_kinds
    ]
    config["reference_monitor_policy"] = "local-flow-v1"
    config["benchmark_corpus_revision"] = (
        "nexus-synthetic-v1" if "campaign" in committed else "legacy-local-corpus-v1"
    )
    results = {
        "evaluation_id": str(evaluation.id),
        "terminal_status": manifest["terminal_status"],
        "findings": internal_results["red_projection"]
        if profile == "RED_OPERATOR" and evaluation.owner_id == user.id
        else internal_results["metadata_projection"],
        "runtime": internal_results["runtime"],
    }
    projected = {
        **manifest,
        **context,
        "chain": chain,
        "coverage": "AUTHORIZED_PROJECTION_ONLY",
        "disclosed_artifacts": visible_kinds,
        "configuration": config,
        "limitations": [
            "Authenticates included files and this authorized projection only.",
            "This projection cannot verify hidden confidential history or its completeness.",
            "Signatures do not prove truth, host integrity, model safety or successful cleanup.",
        ],
    }
    return seal_bundle(projected, events, filtered, results, key, signed_at=timestamp())


def finalize(engine, request_id, key, keyring, *, lock_dir, owner, runtime_uid=None):
    with Session(engine) as lookup:
        queued = lookup.get(EvidenceRequest, request_id)
        if queued is None or queued.state != "PENDING":
            return False
        eid = queued.evaluation_id
    with SigningClaim(
        engine, eid, owner, lock_dir, os.getuid() if runtime_uid is None else runtime_uid
    ) as claim:
        if not claim.acquired:
            return False
        with Session(engine) as db, db.begin():
            evaluation = locked(db, eid)
            queued = db.scalar(
                select(EvidenceRequest).where(EvidenceRequest.id == request_id).with_for_update()
            )
            if queued is None or queued.state != "PENDING":
                return False
            user = db.get(
                User, queued.subject_id, options=[load_only(User.id, User.role, User.is_active)]
            )
            if not member(db, user, eid):
                queued.state, queued.reason_code = "FAILED", "NOT_AUTHORIZED"
                return False
            if evaluation.status not in TERMINAL or evaluation.sealed_at is None:
                queued.state, queued.reason_code = "FAILED", "CLOSED_SEALED_SNAPSHOT_REQUIRED"
                return False
            if not evaluation.proof_native and not queued.retrospective:
                queued.state, queued.reason_code = "FAILED", "EXPLICIT_RETROSPECTIVE_REQUIRED"
                return False
            snapshot = db.scalar(
                select(EvidenceSnapshot).where(
                    EvidenceSnapshot.evaluation_id == eid,
                    EvidenceSnapshot.watermark == evaluation.event_sequence,
                )
            )
            if snapshot is None:
                snapshot = make_snapshot(db, evaluation, key)
            receipt = db.scalar(
                select(EvidenceReceipt).where(
                    EvidenceReceipt.snapshot_id == snapshot.id,
                    EvidenceReceipt.subject_id == user.id,
                    EvidenceReceipt.profile == user.role,
                )
            )
            if receipt is None:
                blob = project(db, evaluation, snapshot, user, key, keyring)
                if verify(blob, keyring).status != "VALID":
                    raise ValueError("PROJECTION_VERIFICATION_FAILED")
                receipt = EvidenceReceipt(
                    evaluation_id=eid,
                    snapshot_id=snapshot.id,
                    subject_id=user.id,
                    profile=user.role,
                    watermark=snapshot.watermark,
                    envelope=parse(blob)["receipt"],
                    bundle=blob,
                )
                db.add(receipt)
                db.flush()
            claim.check()
            queued.state, queued.receipt_id, queued.reason_code = "SIGNED", receipt.id, None
            return True
