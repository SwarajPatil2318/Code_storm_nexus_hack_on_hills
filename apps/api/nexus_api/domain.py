from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from nexus_api.access import AccessError
from nexus_api.auth import DB, Identity, audit, deny, require_role
from nexus_api.authorization import (
    artifact_for,
    artifact_is_sealed,
    can_see_event,
    evaluation_for,
    membership_clause,
    serialize_event,
)
from nexus_api.domain_schemas import (
    ArtifactCreate,
    ArtifactResponse,
    ArtifactUpdate,
    EvaluationResponse,
    PolicyResponse,
    PrivateContentResponse,
    ResultMetadata,
    ResultResponse,
)
from nexus_api.events import (
    EventSource,
    EventType,
    PermittedMetadata,
    SecurityEventResponse,
    Visibility,
)
from nexus_api.identity_schemas import Role
from nexus_api.models import (
    Artifact,
    AuthAudit,
    Evaluation,
    EvaluationResult,
    Policy,
    SecurityEvent,
)

router = APIRouter(tags=["authorized workspace"])


@router.get("/artifacts", response_model=list[ArtifactResponse])
def artifacts(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.RED, Role.BLUE)
    kind = "attack" if identity.user.role == Role.RED else "defence"
    records = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.owner_id == identity.user.id, Artifact.kind == kind)
            .order_by(Artifact.created_at.desc())
            .limit(200)
        )
    )
    sealed_ids = (
        set(
            db.scalars(
                select(Evaluation.defence_artifact_id).where(
                    Evaluation.sealed_at.is_not(None),
                    Evaluation.defence_artifact_id.in_([record.id for record in records]),
                )
            )
        )
        if records
        else set()
    )
    return [
        ArtifactResponse.model_validate(record).model_copy(
            update={"content_restricted": record.sealed_at is not None or record.id in sealed_ids}
        )
        for record in records
    ]


@router.post("/artifacts", response_model=ArtifactResponse, status_code=201)
def create_artifact(body: ArtifactCreate, request: Request, db: DB, identity: Identity):
    expected = Role.RED if body.kind == "attack" else Role.BLUE
    require_role(db, request, identity, expected)
    artifact = Artifact(
        owner_id=identity.user.id, name=body.name, kind=body.kind, private_content=body.content
    )
    db.add(artifact)
    audit(db, request, EventType.ARTIFACT_COMMITTED, identity.user.id, "OWNED_ARTIFACT_CREATED")
    db.commit()
    return artifact


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: UUID, request: Request, db: DB, identity: Identity):
    artifact = artifact_for(db, request, identity, artifact_id)
    return ArtifactResponse.model_validate(artifact).model_copy(
        update={"content_restricted": artifact_is_sealed(db, artifact)}
    )


@router.get("/artifacts/{artifact_id}/content", response_model=PrivateContentResponse)
def artifact_content(artifact_id: UUID, request: Request, db: DB, identity: Identity):
    artifact = artifact_for(db, request, identity, artifact_id)
    if artifact_is_sealed(db, artifact):
        deny(db, request, identity, "sealed_content_restricted")
    return PrivateContentResponse(id=artifact.id, content=artifact.private_content or "")


@router.patch("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def update_artifact(
    artifact_id: UUID, body: ArtifactUpdate, request: Request, db: DB, identity: Identity
):
    artifact = artifact_for(db, request, identity, artifact_id)
    if artifact_is_sealed(db, artifact):
        deny(db, request, identity, "sealed_artifact_immutable")
    artifact.name = body.name
    audit(db, request, EventType.ARTIFACT_UPDATED, identity.user.id, "OWNED_ARTIFACT_RENAMED")
    db.commit()
    return artifact


@router.delete("/artifacts/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: UUID, request: Request, db: DB, identity: Identity):
    artifact = artifact_for(db, request, identity, artifact_id)
    if artifact_is_sealed(db, artifact):
        deny(db, request, identity, "sealed_artifact_immutable")
    db.delete(artifact)
    audit(db, request, EventType.ARTIFACT_DELETED, identity.user.id, "OWNED_ARTIFACT_DELETED")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AccessError(
            409, "artifact_in_use", "This artifact is referenced by another record"
        ) from None


@router.get("/policies/{policy_id}", response_model=PolicyResponse)
def policy(policy_id: UUID, request: Request, db: DB, identity: Identity):
    record = db.scalar(
        select(Policy).where(Policy.id == policy_id, Policy.owner_id == identity.user.id)
    )
    if identity.user.role != Role.BLUE or record is None:
        deny(db, request, identity, "not_found", 404)
    if db.scalar(
        select(Evaluation.id)
        .where(Evaluation.policy_id == policy_id, Evaluation.sealed_at.is_not(None))
        .limit(1)
    ):
        deny(db, request, identity, "sealed_content_restricted")
    return record


@router.get("/evaluations", response_model=list[EvaluationResponse])
def evaluations(db: DB, identity: Identity):
    return list(
        db.scalars(
            select(Evaluation)
            .where(membership_clause(identity.user.id))
            .order_by(Evaluation.created_at.desc())
            .limit(200)
        )
    )


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationResponse)
def evaluation(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    return evaluation_for(db, request, identity, evaluation_id)


@router.get("/evaluations/{evaluation_id}/result", response_model=ResultResponse)
def result(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.RED, Role.BLUE, Role.AUDITOR)
    evaluation_for(db, request, identity, evaluation_id)
    record = db.scalar(
        select(EvaluationResult).where(EvaluationResult.evaluation_id == evaluation_id)
    )
    if record is None:
        raise AccessError(404, "not_found", "No result is available")
    clean = {}
    for key, value in record.summary.items():
        if key not in ResultMetadata.model_fields:
            continue
        try:
            clean.update(ResultMetadata.model_validate({key: value}).model_dump(exclude_none=True))
        except ValidationError:
            continue
    return ResultResponse(evaluation_id=evaluation_id, summary=ResultMetadata(**clean))


@router.get("/evaluations/{evaluation_id}/events", response_model=list[SecurityEventResponse])
def evaluation_events(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    record = evaluation_for(db, request, identity, evaluation_id)
    # Restrict at query time; private records must not consume a visible page.
    visible = [SecurityEvent.visibility == Visibility.EVALUATION]
    if identity.user.role == Role.AUDITOR:
        visible.append(SecurityEvent.visibility == Visibility.AUDITOR)
    elif identity.user.role == Role.RED:
        visible.append(
            and_(
                SecurityEvent.visibility == Visibility.RED,
                SecurityEvent.subject_user_id == identity.user.id,
            )
        )
    elif identity.user.role == Role.BLUE and record.sealed_at is None:
        visible.append(
            and_(
                SecurityEvent.visibility == Visibility.BLUE,
                SecurityEvent.subject_user_id == identity.user.id,
            )
        )
    events = db.scalars(
        select(SecurityEvent)
        .where(SecurityEvent.evaluation_id == evaluation_id, or_(*visible))
        .order_by(
            SecurityEvent.sequence.asc().nulls_last(), SecurityEvent.created_at, SecurityEvent.id
        )
        .limit(200)
    )
    output = []
    for event in events:
        if can_see_event(identity.user, event, record):
            serialized = serialize_event(event)
            if serialized is not None:
                output.append(serialized)
                if len(output) == 200:
                    break
    return output


@router.get("/audit-events", response_model=list[SecurityEventResponse])
def application_events(db: DB, identity: Identity):
    query = select(AuthAudit).order_by(AuthAudit.created_at.desc()).limit(100)
    if identity.user.role != Role.ADMIN:
        query = query.where(AuthAudit.actor_id == identity.user.id)
    events = db.scalars(query)
    return [
        SecurityEventResponse(
            event_id=event.id,
            evaluation_id=None,
            event_type=event.event_type,
            timestamp=event.created_at,
            source=EventSource.IDENTITY_SERVICE
            if event.event_type.startswith("AUTH_")
            else EventSource.API,
            destination=EventSource.API,
            visibility=Visibility.OPERATOR
            if event.actor_id == identity.user.id
            else Visibility.OPERATIONAL,
            permitted_metadata=PermittedMetadata(reason_code=event.reason_code),
            correlation_id=event.correlation_id,
            origin="APPLICATION",
        )
        for event in events
    ]
