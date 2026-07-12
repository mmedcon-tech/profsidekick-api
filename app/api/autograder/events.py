from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.database.models import User
from app.dependencies.auth import get_current_user
from app.llm.confirmation_bus import confirmation_bus
from app.llm.event_bus import event_bus

router = APIRouter(prefix="/api/autograder", tags=["autograder-events"])


@router.get("/grade/events/{request_id}")
async def grade_events(
    request_id: str,
    current_user: User = Depends(get_current_user),
):
    """SSE stream — open BEFORE posting to /grade. Closes on grading_complete or grading_failed."""

    print(
        f"[TRACE] sse_connected request_id={request_id} "
        f"user_id={current_user.id}"
    )

    async def stream():
        events_delivered = 0
        queue = event_bus.register(request_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    print(f"[TRACE] sse_heartbeat request_id={request_id}")
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue

                events_delivered += 1
                print(
                    f"[TRACE] sse_event_delivered request_id={request_id} "
                    f"event_type={event['event']} "
                    f"provider={event.get('provider')} "
                    f"seq={events_delivered}"
                )
                yield f"event: {event['event']}\ndata: {json.dumps(event)}\n\n"

                if event["event"] in ("grading_complete", "grading_failed"):
                    print(
                        f"[TRACE] sse_terminal_event request_id={request_id} "
                        f"event={event['event']} closing_stream=True"
                    )
                    break
        finally:
            print(
                f"[TRACE] sse_disconnected request_id={request_id} "
                f"events_delivered={events_delivered}"
            )
            event_bus.unregister(request_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class GradingConfirmRequest(BaseModel):
    continue_grading: bool


@router.post("/grade/confirm/{request_id}", status_code=status.HTTP_200_OK)
async def grade_confirm(
    request_id: str,
    body: GradingConfirmRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Deliver the publisher's decision after a confirmation_required SSE event.

    Called by the frontend when the publisher clicks "Continue with OpenAI" or
    "Cancel submission" in the fallback confirmation dialog.

    Returns 200 if the decision was delivered to the waiting grading coroutine.
    Returns 404 if no grading job is currently paused for this request_id
    (e.g. the 180-second timeout already fired).
    """
    delivered = confirmation_bus.resolve(request_id, body.continue_grading)
    if not delivered:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No grading job is currently awaiting confirmation for this "
                "request_id. The confirmation window may have expired."
            ),
        )
    print(
        f"[TRACE] grade_confirm request_id={request_id} "
        f"continue_grading={body.continue_grading} "
        f"user_id={current_user.id}"
    )
    return {"request_id": request_id, "continue_grading": body.continue_grading}
