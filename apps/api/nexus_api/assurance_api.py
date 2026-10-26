"""Authenticated view of immutable operator attestations, with explicit evidence scope."""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from nexus_api.access import AccessError
from nexus_api.assurance_schemas import AssuranceReport
from nexus_api.assurance_workspace import AssuranceRecord, model_for, records
from nexus_api.auth import DB, Identity, require_role
from nexus_api.authorization import evaluation_for, membership_clause
from nexus_api.campaign_schemas import ModelManifest
from nexus_api.models import ArtifactVersion, Evaluation
from nexus_api.runtime_api import runtime as runtime_view
from nexus_api.runtime_dto import RuntimeResponse
from nexus_api.schema_base import Strict
from nexus_api.versioning import verified_content

router = APIRouter(tags=["LLM assurance"])


class AssuranceView(Strict):
    evaluation_id: UUID
    state: str
    report: AssuranceReport | None
    model: ModelManifest | None = None
    runtime: RuntimeResponse | None = None


@router.get("/assurance/evaluations", response_model=list[AssuranceRecord])
def listing(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, "RED_OPERATOR", "AUDITOR")
    return records(db, identity, ["assurance_report"])


@router.get("/assurance/evaluations/{evaluation_id}", response_model=AssuranceView)
def details(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = evaluation_for(db, request, identity, evaluation_id)
    require_role(db, request, identity, "RED_OPERATOR", "AUDITOR")
    value = (
        verified_content(db.get(ArtifactVersion, evaluation.red_version_id))
        if evaluation.red_version_id
        else {}
    )
    report = value.get("assurance_report")
    model = model_for(db, evaluation)
    runtime = runtime_view(evaluation_id, request, db, identity)
    if not report:
        if model and model.provider == "local" and runtime.snapshot:
            return AssuranceView(
                evaluation_id=evaluation.id,
                state=evaluation.status,
                report=None,
                model=model,
                runtime=runtime,
            )
        raise AccessError(404, "not_found", "No compatible model evidence is available")
    report = AssuranceReport.model_validate(report)
    # References do not grant membership or reveal evaluations to unrelated users.
    allowed = set(db.scalars(select(Evaluation.id).where(membership_clause(identity.user.id))))
    observations = [
        o.model_copy(
            update={
                "evidence_evaluations": [eid for eid in o.evidence_evaluations if eid in allowed]
            }
        )
        for o in report.observations
    ]
    return AssuranceView(
        evaluation_id=evaluation.id,
        state=evaluation.status,
        report=report.model_copy(update={"observations": observations}),
        model=model,
        runtime=runtime,
    )
