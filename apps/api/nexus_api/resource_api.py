"""Authenticated view of immutable operator attestations, with explicit evidence scope."""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from nexus_api.access import AccessError
from nexus_api.assurance_workspace import AssuranceRecord, model_for, records
from nexus_api.auth import DB, Identity, require_role
from nexus_api.authorization import evaluation_for, membership_clause
from nexus_api.campaign_schemas import ModelManifest
from nexus_api.models import ArtifactVersion, Evaluation, RuntimeRecord
from nexus_api.resource_schemas import ResourceReport
from nexus_api.runtime_api import runtime as runtime_view
from nexus_api.runtime_dto import IsolationView, RuntimeResponse
from nexus_api.schema_base import Strict
from nexus_api.timing_schemas import TimingReport
from nexus_api.versioning import verified_content

router = APIRouter(tags=["Resource assurance"])


class ResourceView(Strict):
    evaluation_id: UUID
    state: str
    report: ResourceReport | None
    timing_report: TimingReport | None = None
    isolation: IsolationView | None = None
    model: ModelManifest | None = None
    runtime: RuntimeResponse | None = None


@router.get("/resource-assurance/evaluations", response_model=list[AssuranceRecord])
def listing(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, "RED_OPERATOR", "AUDITOR")
    return records(db, identity, ["resource_report", "timing_report"])


@router.get("/resource-assurance/evaluations/{evaluation_id}", response_model=ResourceView)
def details(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = evaluation_for(db, request, identity, evaluation_id)
    require_role(db, request, identity, "RED_OPERATOR", "AUDITOR")
    if not evaluation.red_version_id:
        raise AccessError(404, "not_found", "No experiment attestation is available")
    model = model_for(db, evaluation)
    runtime_data = runtime_view(evaluation_id, request, db, identity)
    value = verified_content(db.get(ArtifactVersion, evaluation.red_version_id))
    report = value.get("resource_report")
    timing = value.get("timing_report")
    if timing:
        timing = TimingReport.model_validate(timing)
        allowed = set(db.scalars(select(Evaluation.id).where(membership_clause(identity.user.id))))
        timing = timing.model_copy(
            update={
                field: getattr(timing, field).model_copy(
                    update={
                        "evaluation_ids": [
                            eid for eid in getattr(timing, field).evaluation_ids if eid in allowed
                        ]
                    }
                )
                for field in ["standard", "reduced"]
            }
        )
        runtime = db.get(RuntimeRecord, evaluation.id)
        return ResourceView(
            evaluation_id=evaluation.id,
            state=evaluation.status,
            report=None,
            timing_report=timing,
            isolation=runtime.snapshot.get("isolation") if runtime else None,
            model=model,
            runtime=runtime_data,
        )
    if not report:
        if model and model.provider == "local" and runtime_data.snapshot:
            return ResourceView(
                evaluation_id=evaluation.id,
                state=evaluation.status,
                report=None,
                model=model,
                runtime=runtime_data,
            )
        raise AccessError(404, "not_found", "No compatible resource evidence is available")
    report = ResourceReport.model_validate(report)
    # References do not grant membership or reveal evaluations to unrelated users.
    allowed = set(db.scalars(select(Evaluation.id).where(membership_clause(identity.user.id))))
    observations = [
        o.model_copy(update={"evaluation_ids": [eid for eid in o.evaluation_ids if eid in allowed]})
        for o in report.observations
    ]
    return ResourceView(
        evaluation_id=evaluation.id,
        state=evaluation.status,
        report=report.model_copy(update={"observations": observations}),
        model=model,
        runtime=runtime_data,
    )
