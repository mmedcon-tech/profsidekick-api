from __future__ import annotations

import asyncio

_QUEUE_TTL_SECONDS = 600


class EventBus:
    """In-memory SSE event bus. Maps request_id → asyncio.Queue."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        self._ttl_tasks: dict[str, asyncio.Task] = {}

    def register(self, request_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues[request_id] = q
        print(
            f"[TRACE] event_bus_register request_id={request_id} "
            f"active_queues={len(self._queues)}"
        )
        try:
            task = asyncio.get_running_loop().create_task(
                self._expire(request_id), name=f"evbus-ttl-{request_id}"
            )
            self._ttl_tasks[request_id] = task
        except RuntimeError:
            pass
        return q

    async def _expire(self, request_id: str) -> None:
        await asyncio.sleep(_QUEUE_TTL_SECONDS)
        print(f"[TRACE] event_bus_ttl_expired request_id={request_id}")
        self.unregister(request_id)

    async def publish(self, request_id: str, event: dict) -> None:
        q = self._queues.get(request_id)
        if q is None:
            print(
                f"[TRACE] event_bus_publish_dropped request_id={request_id} "
                f"event={event.get('event')} reason=no_queue_registered"
            )
            return
        await q.put(event)
        print(
            f"[TRACE] event_bus_publish request_id={request_id} "
            f"event_type={event.get('event')} "
            f"provider={event.get('provider')} "
            f"queue_size={q.qsize()}"
        )

    def unregister(self, request_id: str) -> None:
        was_registered = request_id in self._queues
        self._queues.pop(request_id, None)
        task = self._ttl_tasks.pop(request_id, None)
        if task and not task.done():
            task.cancel()
        if was_registered:
            print(
                f"[TRACE] event_bus_unregister request_id={request_id} "
                f"active_queues={len(self._queues)}"
            )


event_bus = EventBus()
