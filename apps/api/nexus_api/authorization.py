"""No administrative bypass: role, object ownership and evaluation membership are distinct."""

from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from nexus_api.auth import Principal, deny
from nexus_api.events import (
    EventSource,
    EventType,
    SecurityEventResponse,
    Visibility,
    sanitize_metadata,
)
from nexus_api.identity_schemas import Role
from nexus_api.models import Artifact, Evaluation, EvaluationMembership, SecurityEvent


def member_evaluations(user_id):
    return select(EvaluationMembership.evaluation_id).where(EvaluationMembership.user_id == user_id)


def membership_clause(user_id):
    return or_(Evaluation.owner_id == user_id, Evaluation.id.in_(member_evaluations(user_id)))


def evaluation_for(db: Session, request: Request, identity: Principal, evaluation_id) -> Evaluation:
    evaluation = db.scalar(
        select(Evaluation).where(
            Evaluation.id == evaluation_id, membership_clause(identity.user.id)
        )
    )
    if evaluation is None:
        # Do not reveal whether another principal's object exists.
        deny(db, request, identity, "not_found", 404)
    return evaluation


def artifact_for(db: Session, request: Request, identity: Principal, artifact_id) -> Artifact:
    kind = {Role.RED: "attack", Role.BLUE: "defence"}.get(identity.user.role)
    artifact = (
        db.scalar(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.owner_id == identity.user.id,
                Artifact.kind == kind,
            )
        )
        if kind
        else None
    )
    if artifact is None:
        deny(db, request, identity, "not_found", 404)
    return artifact


def artifact_is_sealed(db: Session, artifact: Artifact) -> bool:
    if artifact.sealed_at is not None:
        return True
    # Read-only support for future sealed records, not an implemented sealing operation.
    return (
        db.scalar(
            select(Evaluation.id)
            .where(Evaluation.defence_artifact_id == artifact.id, Evaluation.sealed_at.is_not(None))
            .limit(1)
        )
        is not None
    )


def can_see_event(user, event: SecurityEvent, evaluation: Evaluation) -> bool:
    if event.visibility == Visibility.EVALUATION:
        return True  # Caller must have already enforced evaluation membership.
    if event.visibility == Visibility.AUDITOR:
        return user.role == Role.AUDITOR
    if event.visibility == Visibility.RED:
        return user.role == Role.RED and event.subject_user_id == user.id
    if event.visibility == Visibility.BLUE:
        return (
            user.role == Role.BLUE
            and event.subject_user_id == user.id
            and evaluation.sealed_at is None
        )
    return False


def serialize_event(event: SecurityEvent) -> SecurityEventResponse | None:
    # Historical/unrecognized categories never become a generic raw event escape hatch.
    if event.event_type not in EventType._value2member_map_:
        return None
    if event.source not in EventSource._value2member_map_:
        return None
    if event.destination not in EventSource._value2member_map_:
        return None
    return SecurityEventResponse(
        event_id=event.id,
        sequence=event.sequence,
        evaluation_id=event.evaluation_id,
        event_type=event.event_type,
        timestamp=event.created_at,
        source=event.source,
        destination=event.destination,
        visibility=event.visibility,
        permitted_metadata=sanitize_metadata(event.event_metadata),
        correlation_id=event.correlation_id,
        origin="RUNTIME",
    )
