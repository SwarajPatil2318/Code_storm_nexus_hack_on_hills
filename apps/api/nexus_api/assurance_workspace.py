"""Discovery metadata only; dedicated attestations remain distinct from native runs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select

from nexus_api.authorization import membership_clause
from nexus_api.campaign_schemas import ModelManifest
from nexus_api.models import ArtifactVersion, Evaluation, RuntimeRecord
from nexus_api.schema_base import Strict
from nexus_api.versioning import verified_content


class AssuranceRecord(Strict):
    evaluation_id: UUID
    name: str
    state: str
    created_at: datetime
    model_id: str
    record_kind: Literal["EVALUATION", "EXPERIMENT"]
    has_runtime: bool


def model_for(db, evaluation):
    record = (
        db.get(ArtifactVersion, evaluation.model_version_id)
        if evaluation.model_version_id
        else None
    )
    if not record:
        return None
    value = verified_content(record)
    # Pre-campaign mock records use an adapter/mode object, not a model manifest.
    # They are not compatible model evidence and must not poison discovery.
    if value.get("schema_version") != "model-manifest-v1":
        return None
    return ModelManifest.model_validate(value)


def records(db, identity, fields):
    # Inspect at most 500 recent member records, then select compatible evidence.
    # No payload/policy is serialized; existing role gates run before this helper.
    rows = db.scalars(
        select(Evaluation)
        .where(membership_clause(identity.user.id))
        .order_by(Evaluation.created_at.desc(), Evaluation.id.desc())
        .limit(500)
    )
    result = []
    for row in rows:
        model = model_for(db, row)
        runtime = db.get(RuntimeRecord, row.id)
        corpus = (
            verified_content(db.get(ArtifactVersion, row.red_version_id))
            if row.red_version_id
            else {}
        )
        experiment = any(corpus.get(field) for field in fields)
        if experiment or (model and model.provider == "local" and runtime and runtime.snapshot):
            result.append(
                AssuranceRecord(
                    evaluation_id=row.id,
                    name=row.name,
                    state=row.status,
                    created_at=row.created_at,
                    model_id=model.model_id if model else "Not recorded",
                    record_kind="EXPERIMENT" if experiment else "EVALUATION",
                    has_runtime=bool(runtime and runtime.snapshot),
                )
            )
    return result
