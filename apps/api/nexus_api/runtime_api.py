"""Existing session/CSRF/role/member boundary for safe runtime data and fixed probe actions."""

from uuid import UUID

from fastapi import APIRouter, Request

from nexus_api.auth import DB, Identity
from nexus_api.authorization import evaluation_for
from nexus_api.evaluation_api import local_evaluation, owner
from nexus_api.models import EvaluationJob, RuntimeRecord
from nexus_api.runtime_client import control
from nexus_api.runtime_dto import RuntimeCapabilities, RuntimeResponse

router = APIRouter(tags=["isolated runtime"])


@router.get("/runtime/capabilities", response_model=RuntimeCapabilities)
def capabilities(request: Request, identity: Identity):
    try:
        return control(request.app.state.settings, "capabilities", UUID(int=0), identity.user.id)
    except Exception:
        return RuntimeCapabilities(
            available=False,
            reason="Start the confined API and trusted provisioner profile",
            profile="unavailable",
            cgroups="unverified",
            seccomp=False,
        )


@router.get("/evaluations/{evaluation_id}/runtime", response_model=RuntimeResponse)
def runtime(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = evaluation_for(db, request, identity, evaluation_id)
    record = db.get(RuntimeRecord, evaluation_id)
    job = db.get(EvaluationJob, evaluation_id)
    return RuntimeResponse(
        evaluation_id=evaluation_id,
        execution_mode=evaluation.execution_mode,
        snapshot=record.snapshot if record else None,
        updated_at=record.updated_at if record else None,
        recovery_state=job.state if job else None,
        cleanup_status=job.cleanup if job else None,
        credentials_revoked=job.credentials_revoked if job else None,
        recovery_reason=job.reason_code if job else None,
    )


@router.post("/evaluations/{evaluation_id}/probes", status_code=202)
def probes(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    owner(db, request, identity, evaluation)
    db.rollback()
    return control(request.app.state.settings, "probes", evaluation_id, identity.user.id)
