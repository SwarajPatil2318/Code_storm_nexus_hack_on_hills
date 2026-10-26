"""Unified read-only assurance, always authorized before evidence lookup/decoding."""

from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import select

from nexus_api import center_archive as archive
from nexus_api.access import AccessError
from nexus_api.auth import DB, Identity, require_role
from nexus_api.authorization import evaluation_for, membership_clause
from nexus_api.center_analysis import derive, objectives
from nexus_api.center_schemas import (
    ArchivedExperiment,
    ArchiveHistory,
    CenterEvaluation,
    CenterFinding,
    CenterSource,
    CenterView,
)
from nexus_api.events import EventType, sanitize_metadata
from nexus_api.models import ArtifactVersion, Evaluation, EvidenceReceipt, RuntimeRecord
from nexus_api.proof_service import ROLES
from nexus_api.runtime_dto import RuntimeSnapshot
from nexus_api.versioning import verified_content

router = APIRouter(tags=["Assurance Center"])


def available_archives(request, identity):
    c, condition = archive.catalog(request.app.state.settings)
    return (
        c,
        condition,
        [(e, g) for e in (c.entries if c else []) if (g := archive.permitted(e, identity.user))],
    )


def archive_for(aid, request, db, identity):
    require_role(db, request, identity, *sorted(ROLES))
    c, _, entries = available_archives(request, identity)
    entry = next(((e, g) for e, g in entries if e.id == aid), None)
    if not entry:
        raise AccessError(404, "not_found", "Evidence is not available")
    return archive.load(*entry, c, request.app.state.settings)


def audit_finding(source):
    valid = source.verification and source.verification.status == "VALID"
    return CenterFinding(
        id=source.id + "-integrity",
        objective="audit",
        title="Evidence integrity and trust",
        outcome="PASS"
        if valid
        else "FAIL"
        if source.condition == "INVALID"
        else "INCONCLUSIVE"
        if source.condition in {"UNTRUSTED", "INCOMPLETE"}
        else "NOT_TESTED",
        source_id=source.id,
        detail=(
            "Integrity and trust describe these recorded bytes. Signed "
            "projections do not prove hidden completeness, event truth or host "
            "integrity."
        ),
        measurements={
            "evidence_condition": source.condition,
            "signature_valid": bool(source.verification and source.verification.signature_valid),
            "signer_trusted": bool(source.verification and source.verification.signer_trusted),
            "coverage": source.coverage,
        },
        provenance="RECORDED_APPLICATION",
    )


def view(sources, findings, condition):
    return CenterView(
        sources=sources,
        objectives=objectives(findings),
        catalog_condition=condition,
        unresolved_risk=(
            "Residual timing leakage remains FAIL where recorded. Complete "
            "side-channel confidentiality and physical erasure are not proven; "
            "untrusted or missing evidence cannot establish a passing control."
        ),
    )


@router.get("/assurance-center", response_model=CenterView)
def overview(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, *sorted(ROLES))
    c, condition, entries = available_archives(request, identity)
    sources, findings = [], []
    for e, g in entries:
        source, data, _ = archive.load(e, g, c, request.app.state.settings)
        findings.append(audit_finding(source))
        if data and source.condition == "AVAILABLE":
            try:
                findings.extend(derive(source.id, data["results"].get("runtime"), data["corpus"]))
            except (ValueError, ValidationError, TypeError, KeyError):
                source = source.model_copy(update={"condition": "STALE"})
        sources.append(source)
    return view(sources, findings, condition)


@router.get("/assurance-center/evaluations", response_model=list[CenterEvaluation])
def listing(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, *sorted(ROLES))
    rows = db.scalars(
        select(Evaluation)
        .where(membership_clause(identity.user.id))
        .order_by(Evaluation.created_at.desc())
        .limit(100)
    )
    return [{"id": str(e.id), "name": e.name, "state": e.status} for e in rows]


@router.get("/assurance-center/evaluations/{eid}", response_model=CenterView)
def local(eid: UUID, request: Request, db: DB, identity: Identity):
    e = evaluation_for(db, request, identity, eid)
    require_role(db, request, identity, *sorted(ROLES))
    # Never read a private attack corpus for Blue or an unrelated auditor.
    corpus = {}
    if identity.user.role == "RED_OPERATOR" and e.owner_id == identity.user.id and e.red_version_id:
        corpus = verified_content(db.get(ArtifactVersion, e.red_version_id))
    runtime = db.get(RuntimeRecord, e.id)
    source = CenterSource(
        id="local-" + str(eid),
        environment="CURRENT_DATABASE",
        evaluation_id=eid,
        profile=identity.user.role,
        condition="NOT_VERIFIED",
        coverage="MEMBER_AUTHORIZED_VIEW",
        provenance="RECORDED_APPLICATION",
        proof_url="/proof-vault?evaluation=" + str(eid),
        trace_url="/x-ray?evaluation=" + str(eid),
    )
    # Receipt existence alone is not cryptographic verification. Proof Vault does that.
    receipt = db.scalar(
        select(EvidenceReceipt.id)
        .where(
            EvidenceReceipt.evaluation_id == eid,
            EvidenceReceipt.subject_id == identity.user.id,
            EvidenceReceipt.profile == identity.user.role,
        )
        .limit(1)
    )
    findings = derive(source.id, runtime.snapshot if runtime else None, corpus)
    findings.append(
        CenterFinding(
            id=source.id + "-receipt",
            objective="audit",
            title="Proof Vault evidence",
            outcome="NOT_TESTED",
            source_id=source.id,
            detail=(
                "A matching receipt is available in Proof Vault; verify the original bytes there."
            )
            if receipt
            else "No matching signed receipt is available for this identity.",
            provenance="RECORDED_APPLICATION",
            measurements={"receipt_available": bool(receipt)},
        )
    )
    return view([source], findings, "NOT_CONFIGURED")


@router.get("/assurance-center/archives/{aid}", response_model=CenterSource)
def archive_details(aid: UUID, request: Request, db: DB, identity: Identity):
    return archive_for(aid, request, db, identity)[0]


@router.get("/assurance-center/experiments/{aid}", response_model=ArchivedExperiment)
def experiment_details(aid: UUID, request: Request, db: DB, identity: Identity):
    # The archive grant is checked before bytes are decoded; Blue never gains
    # access to a Red report corpus through a new presentation endpoint.
    require_role(db, request, identity, "RED_OPERATOR", "AUDITOR")
    source, data, _ = archive_for(aid, request, db, identity)
    if source.condition != "AVAILABLE" or data is None:
        raise AccessError(
            409, "evidence_unavailable", "Verified experiment evidence is unavailable"
        )
    c, _, entries = available_archives(request, identity)
    allowed = {e.evaluation_id for e, _ in entries}
    reports = {}
    from nexus_api.assurance_schemas import AssuranceReport
    from nexus_api.resource_schemas import ResourceReport
    from nexus_api.timing_schemas import TimingReport

    for field, schema, references in [
        ("assurance_report", AssuranceReport, "evidence_evaluations"),
        ("resource_report", ResourceReport, "evaluation_ids"),
        ("timing_report", TimingReport, "evaluation_ids"),
    ]:
        raw = data["corpus"].get(field)
        if not raw:
            continue
        report = schema.model_validate(raw)
        if field == "timing_report":
            report = report.model_copy(
                update={
                    key: getattr(report, key).model_copy(
                        update={
                            references: [
                                eid for eid in getattr(report, key).evaluation_ids if eid in allowed
                            ]
                        }
                    )
                    for key in ["standard", "reduced"]
                }
            )
        else:
            report = report.model_copy(
                update={
                    "observations": [
                        o.model_copy(
                            update={
                                references: [
                                    eid for eid in getattr(o, references) if eid in allowed
                                ]
                            }
                        )
                        for o in report.observations
                    ]
                }
            )
        reports[field] = report
    if not reports:
        raise AccessError(404, "not_found", "No compatible experiment is recorded")
    # Only separately granted original sources get links; never point an old UUID
    # into the current database or turn a report reference into membership.
    related_sources = [
        archive.load(e, g, c, request.app.state.settings)[0]
        for e, g in entries
        if e.evaluation_id in allowed
    ]
    runtime = data["results"].get("runtime")
    isolation = RuntimeSnapshot.model_validate(runtime).isolation if runtime else None
    return ArchivedExperiment(
        source=source, isolation=isolation, related_sources=related_sources, **reports
    )


@router.get("/assurance-center/archives/{aid}/bundle")
def export(aid: UUID, request: Request, db: DB, identity: Identity):
    source, _, raw = archive_for(aid, request, db, identity)
    if raw is None or source.condition not in {"AVAILABLE", "UNTRUSTED", "STALE"}:
        raise AccessError(409, "evidence_unavailable", "Original evidence cannot be exported")
    return Response(
        raw,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="nexus-original-evidence.json"'},
    )


@router.get(
    "/assurance-center/archives/{aid}/history",
    response_model=ArchiveHistory,
    response_model_exclude_none=True,
)
def history(
    aid: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    after: int = Query(0, ge=0, le=8192),
    limit: int = Query(100, ge=1, le=256),
):
    source, data, _ = archive_for(aid, request, db, identity)
    if source.condition != "AVAILABLE":
        raise AccessError(409, "evidence_unavailable", "Verified history is not available")
    rows = data["events"][after : after + limit]
    events = []
    for e in rows:
        if e["event_type"] not in EventType._value2member_map_:
            continue
        # Only allowlisted metadata, never raw event payloads or artifact openings.
        payload = e["payload"]
        metadata = payload.get("public", payload)
        events.append(
            {
                "sequence": e["sequence"],
                "source_sequence": e["source_sequence"],
                "event_type": e["event_type"],
                "timestamp": e["timestamp"],
                "event_id": e["event_id"],
                "metadata": sanitize_metadata(archive.decimal_values(metadata or {})).model_dump(
                    mode="json", exclude_none=True
                ),
            }
        )
    return {
        "evaluation_id": source.evaluation_id,
        "snapshot_id": source.snapshot_id,
        "events": events,
        "next_after": after + len(rows),
        "has_more": after + len(rows) < len(data["events"]),
        "recorded_events": len(data["events"]),
        "source_watermark": data["manifest"]["source_watermark"],
        "coverage": source.coverage,
    }
