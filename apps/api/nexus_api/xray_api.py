"""Read-only sequence pagination using the existing confidential event projection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import select

from nexus_api.access import AccessError
from nexus_api.auth import DB, Identity
from nexus_api.authorization import can_see_event, evaluation_for, serialize_event
from nexus_api.events import SecurityEventResponse
from nexus_api.models import SecurityEvent
from nexus_api.schema_base import Strict

router = APIRouter(tags=["X-Ray authorized history"])


class HistoryQuery(Strict):
    after: int = Field(default=0, ge=0, le=10**12)
    limit: int = Field(default=128, ge=1, le=256)
    until: int | None = Field(default=None, ge=0, le=10**12)


class HistoryPage(Strict):
    evaluation_id: UUID
    events: list[SecurityEventResponse] = Field(max_length=256)
    next_after: int
    high_watermark: int
    has_more: bool


@router.get("/evaluations/{evaluation_id}/history", response_model=HistoryPage)
def history(
    evaluation_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    query: Annotated[HistoryQuery, Query()],
):
    evaluation = evaluation_for(db, request, identity, evaluation_id)
    watermark = evaluation.event_sequence if query.until is None else query.until
    if query.after > watermark or watermark > evaluation.event_sequence:
        raise AccessError(
            409, "invalid_cursor", "History cursor is outside the recorded evaluation"
        )
    rows = list(
        db.scalars(
            select(SecurityEvent)
            .where(
                SecurityEvent.evaluation_id == evaluation_id,
                SecurityEvent.sequence > query.after,
                SecurityEvent.sequence <= watermark,
            )
            .order_by(SecurityEvent.sequence)
            .limit(query.limit)
        )
    )
    cursor = rows[-1].sequence if rows else watermark
    output = []
    for row in rows:
        if can_see_event(identity.user, row, evaluation):
            projected = serialize_event(row)
            if projected is not None:
                output.append(projected)
    return HistoryPage(
        evaluation_id=evaluation_id,
        events=output,
        next_after=cursor,
        high_watermark=watermark,
        has_more=cursor < watermark,
    )
