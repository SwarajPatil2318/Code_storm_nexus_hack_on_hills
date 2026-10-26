"""Read-only, bounded persisted WebSocket replay. No client-selected identity or event ingestion."""

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from nexus_api.access import AccessError
from nexus_api.auth import principal
from nexus_api.authorization import can_see_event, membership_clause, serialize_event
from nexus_api.events import SecurityEventResponse
from nexus_api.models import Evaluation, SecurityEvent
from nexus_api.runtime_schemas import Strict

router = APIRouter()


class LiveFrame(Strict):
    kind: Literal["event", "cursor"]
    sequence: int = Field(ge=0)
    event: SecurityEventResponse | None = None


def stream_batch(websocket, evaluation_id, cursor):
    # Fresh DB identity checks on every bounded batch enforce expiry/logout/role revocation.
    scope = {**websocket.scope, "type": "http", "method": "GET"}
    request = Request(scope)
    request.state.request_id = str(UUID(int=0))
    with Session(websocket.app.state.engine) as db:
        identity = principal(request, db)
        evaluation = db.scalar(
            select(Evaluation).where(
                Evaluation.id == evaluation_id, membership_clause(identity.user.id)
            )
        )
        if evaluation is None or cursor > evaluation.event_sequence:
            raise AccessError(403, "forbidden", "Subscription is not permitted")
        events = db.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.evaluation_id == evaluation_id, SecurityEvent.sequence > cursor)
            .order_by(SecurityEvent.sequence)
            .limit(64)
        )
        frames = []
        for event in events:
            cursor = event.sequence
            if can_see_event(identity.user, event, evaluation):
                safe = serialize_event(event)
                if safe:
                    frames.append(
                        LiveFrame(kind="event", sequence=cursor, event=safe).model_dump(mode="json")
                    )
        frames.append(LiveFrame(kind="cursor", sequence=cursor).model_dump(mode="json"))
        return frames, cursor


@router.websocket("/evaluations/{evaluation_id}/live")
async def live(websocket: WebSocket, evaluation_id: UUID):
    settings = websocket.app.state.settings
    if (
        websocket.headers.get("origin") not in settings.cors_origins
        or websocket.app.state.engine is None
        or set(websocket.query_params) - {"after"}
    ):
        await websocket.close(code=1008)
        return
    try:
        raw = websocket.query_params.get("after", "0")
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 12:
            raise ValueError
        cursor = int(raw)
        frames, cursor = await asyncio.to_thread(stream_batch, websocket, evaluation_id, cursor)
    except (AccessError, ValueError):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            # No in-memory publish queue: one DB page (64) and per-send deadline bound backpressure.
            for frame in frames:
                await asyncio.wait_for(websocket.send_json(frame), timeout=2)
            try:
                received = await asyncio.wait_for(websocket.receive(), timeout=0.2)
                if received["type"] == "websocket.disconnect":
                    return
                # This is a receive-only subscription. Client data is never interpreted/forwarded.
                await websocket.close(code=1008)
                return
            except TimeoutError:
                pass
            frames, cursor = await asyncio.to_thread(stream_batch, websocket, evaluation_id, cursor)
    except (AccessError, TimeoutError):
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        return
    except SQLAlchemyError:
        await websocket.close(code=1011)
