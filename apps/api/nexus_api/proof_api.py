"""Member-authorized proof projections. No signing key or private snapshot access."""

import asyncio
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, text

from nexus_api.access import AccessError
from nexus_api.auth import DB, Identity, require_role
from nexus_api.authorization import evaluation_for, membership_clause
from nexus_api.models import Evaluation, EvidenceReceipt, EvidenceRequest, EvidenceVerification
from nexus_api.proof_format import MAX_BUNDLE, Receipt, Record, Verification, parse, verify
from nexus_api.proof_service import ROLES, TERMINAL
from nexus_api.schema_base import Strict

router = APIRouter(tags=["Proof Vault"])


class FinalizeBody(Strict):
    retrospective: bool = False


class ProofRequestView(Strict):
    id: UUID
    state: Literal["PENDING", "SIGNED", "FAILED"]
    reason_code: str | None
    receipt_id: UUID | None
    created_at: datetime


class ProofReceiptView(Strict):
    id: UUID
    watermark: int
    receipt: Receipt


class ProofIndex(Strict):
    evaluation_id: UUID
    evaluation_name: str
    terminal_status: str
    evidence_status: Literal["UNSIGNED_LEGACY", "NOT_SIGNED", "PENDING", "SIGNED"]
    current_watermark: int


class ProofView(ProofIndex):
    receipts: list[ProofReceiptView]
    requests: list[ProofRequestView]
    last_verification: Verification | None
    last_verification_target: Literal["STORED_RECEIPT", "SUBMITTED_BUNDLE"] | None


def authorized(eid, request, db, identity):
    evaluation = evaluation_for(db, request, identity, eid)
    require_role(db, request, identity, *sorted(ROLES))
    return evaluation


def receipt_for(eid, rid, request, db, identity):
    authorized(eid, request, db, identity)
    row = db.scalar(
        select(EvidenceReceipt).where(
            EvidenceReceipt.id == rid,
            EvidenceReceipt.evaluation_id == eid,
            EvidenceReceipt.subject_id == identity.user.id,
            EvidenceReceipt.profile == identity.user.role,
        )
    )
    if row is None:
        raise AccessError(404, "not_found", "Evidence is not available")
    return row


def view(evaluation, db, identity):
    receipts = list(
        db.scalars(
            select(EvidenceReceipt)
            .where(
                EvidenceReceipt.evaluation_id == evaluation.id,
                EvidenceReceipt.subject_id == identity.user.id,
                EvidenceReceipt.profile == identity.user.role,
            )
            .order_by(EvidenceReceipt.created_at.desc())
            .limit(20)
        )
    )
    requests = list(
        db.scalars(
            select(EvidenceRequest)
            .where(
                EvidenceRequest.evaluation_id == evaluation.id,
                EvidenceRequest.subject_id == identity.user.id,
            )
            .order_by(EvidenceRequest.created_at.desc())
            .limit(10)
        )
    )
    last = db.scalar(
        select(EvidenceVerification)
        .where(
            EvidenceVerification.evaluation_id == evaluation.id,
            EvidenceVerification.subject_id == identity.user.id,
        )
        .order_by(EvidenceVerification.created_at.desc())
        .limit(1)
    )
    state = (
        "SIGNED"
        if receipts
        else "PENDING"
        if any(r.state == "PENDING" for r in requests)
        else "NOT_SIGNED"
        if evaluation.proof_native
        else "UNSIGNED_LEGACY"
    )
    return ProofView(
        evaluation_id=evaluation.id,
        evaluation_name=evaluation.name,
        terminal_status=evaluation.status,
        evidence_status=state,
        current_watermark=evaluation.event_sequence,
        receipts=[
            ProofReceiptView(
                id=r.id,
                watermark=r.watermark,
                receipt=Receipt.model_validate(r.envelope),
            )
            for r in receipts
        ],
        requests=[ProofRequestView.model_validate(r, from_attributes=True) for r in requests],
        last_verification=Verification.model_validate(last.result) if last else None,
        last_verification_target=("STORED_RECEIPT" if last.receipt_id else "SUBMITTED_BUNDLE")
        if last
        else None,
    )


@router.get("/proof/evaluations", response_model=list[ProofIndex])
def listing(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, *sorted(ROLES))
    rows = db.scalars(
        select(Evaluation)
        .where(membership_clause(identity.user.id), Evaluation.status.in_(TERMINAL))
        .order_by(Evaluation.created_at.desc())
        .limit(100)
    )
    result = []
    for e in rows:
        own = (
            EvidenceReceipt.evaluation_id == e.id,
            EvidenceReceipt.subject_id == identity.user.id,
            EvidenceReceipt.profile == identity.user.role,
        )
        signed = db.scalar(select(EvidenceReceipt.id).where(*own).limit(1))
        pending = db.scalar(
            select(EvidenceRequest.id)
            .where(
                EvidenceRequest.evaluation_id == e.id,
                EvidenceRequest.subject_id == identity.user.id,
                EvidenceRequest.state == "PENDING",
            )
            .limit(1)
        )
        result.append(
            ProofIndex(
                evaluation_id=e.id,
                evaluation_name=e.name,
                terminal_status=e.status,
                evidence_status="SIGNED"
                if signed
                else "PENDING"
                if pending
                else "NOT_SIGNED"
                if e.proof_native
                else "UNSIGNED_LEGACY",
                current_watermark=e.event_sequence,
            )
        )
    return result


@router.get("/proof/evaluations/{evaluation_id}", response_model=ProofView)
def details(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    return view(authorized(evaluation_id, request, db, identity), db, identity)


@router.post(
    "/proof/evaluations/{evaluation_id}/finalize", response_model=ProofRequestView, status_code=202
)
def enqueue(evaluation_id: UUID, body: FinalizeBody, request: Request, db: DB, identity: Identity):
    evaluation = authorized(evaluation_id, request, db, identity)
    if evaluation.status not in TERMINAL or evaluation.sealed_at is None:
        raise AccessError(409, "closed_snapshot_required", "A closed sealed evaluation is required")
    if not evaluation.proof_native and not body.retrospective:
        raise AccessError(
            409,
            "retrospective_required",
            "Legacy evidence requires explicit retrospective attestation",
        )
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:subject, 8))"),
        {"subject": str(identity.user.id)},
    )
    pending = list(
        db.scalars(
            select(EvidenceRequest)
            .where(
                EvidenceRequest.subject_id == identity.user.id, EvidenceRequest.state == "PENDING"
            )
            .limit(5)
        )
    )
    for row in pending:
        if row.evaluation_id == evaluation_id:
            return ProofRequestView.model_validate(row, from_attributes=True)
    if len(pending) >= 4:
        raise AccessError(429, "signing_queue_limit", "Wait for pending evidence requests")
    row = EvidenceRequest(
        evaluation_id=evaluation_id, subject_id=identity.user.id, retrospective=body.retrospective
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ProofRequestView.model_validate(row, from_attributes=True)


@router.get("/proof/evaluations/{evaluation_id}/receipts/{receipt_id}/bundle")
def export(evaluation_id: UUID, receipt_id: UUID, request: Request, db: DB, identity: Identity):
    row = receipt_for(evaluation_id, receipt_id, request, db, identity)
    from nexus_api.models import EvidenceExport

    db.add(
        EvidenceExport(
            evaluation_id=evaluation_id, subject_id=identity.user.id, receipt_id=receipt_id
        )
    )
    db.commit()
    return Response(
        row.bundle,
        media_type="application/vnd.nexus.proof+json",
        headers={"Content-Disposition": f'attachment; filename="nexus-proof-{evaluation_id}.json"'},
    )


def recorded_verification(raw, eid, identity, db, settings, receipt_id=None):
    # Uploaded metadata never grants access to another evaluation or role profile.
    try:
        value = parse(raw)
        scope = value.get("receipt", {}).get("payload", {})
        if (
            scope.get("evaluation_id") != str(eid)
            or scope.get("subject_id") != str(identity.user.id)
            or scope.get("profile") != identity.user.role
        ):
            raise AccessError(
                403, "proof_scope_rejected", "Bundle is outside the authorized evidence scope"
            )
    except (ValueError, TypeError, AttributeError):
        result = Verification(status="INVALID", category="FORMAT")
    else:
        result = verify(raw, settings.proof_trusted_keys)
    db.add(
        EvidenceVerification(
            evaluation_id=eid,
            subject_id=identity.user.id,
            receipt_id=receipt_id,
            result=result.model_dump(),
        )
    )
    db.commit()
    return result


@router.post(
    "/proof/evaluations/{evaluation_id}/receipts/{receipt_id}/verify", response_model=Verification
)
def verify_stored(
    evaluation_id: UUID, receipt_id: UUID, request: Request, db: DB, identity: Identity
):
    row = receipt_for(evaluation_id, receipt_id, request, db, identity)
    return recorded_verification(
        row.bundle, evaluation_id, identity, db, request.app.state.settings, receipt_id
    )


@router.post(
    "/proof/evaluations/{evaluation_id}/verify",
    response_model=Verification,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary", "maxLength": MAX_BUNDLE}
                }
            },
        }
    },
)
async def verify_uploaded(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    authorized(evaluation_id, request, db, identity)
    if request.headers.get("content-encoding", "identity") != "identity":
        raise AccessError(415, "encoding_rejected", "Compressed evidence is not accepted")
    chunks = []
    size = 0
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BUNDLE:
                    raise AccessError(413, "bundle_too_large", "Evidence exceeds the upload limit")
                chunks.append(chunk)
    except TimeoutError:
        raise AccessError(408, "upload_timeout", "Evidence upload deadline exceeded") from None
    # Bounded CPU processing; runs after authentication/CSRF and scoped authorization.
    return recorded_verification(
        b"".join(chunks), evaluation_id, identity, db, request.app.state.settings
    )


@router.get(
    "/proof/evaluations/{evaluation_id}/receipts/{receipt_id}/events/{sequence}",
    response_model=Record,
)
def event_reference(
    evaluation_id: UUID,
    receipt_id: UUID,
    sequence: int,
    request: Request,
    db: DB,
    identity: Identity,
):
    row = receipt_for(evaluation_id, receipt_id, request, db, identity)
    if sequence < 1 or sequence > 8192:
        raise AccessError(
            422, "invalid_sequence", "Evidence sequence is outside the supported range"
        )
    from nexus_api.proof_service import unpack

    events = unpack(row.bundle)[1]
    for event in events:
        if event["source_sequence"] == sequence:
            return event
    raise AccessError(
        404, "not_in_projection", "This event is not included in the authorized snapshot"
    )
