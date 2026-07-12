from __future__ import annotations

import asyncio


class ConfirmationBus:
    """
    Pause-and-resume mechanism for the fallback provider chain.

    When grading reaches the OpenAI transition, the FallbackProvider calls
    wait_for_decision() which blocks until the publisher either confirms
    (continue=True) or cancels (continue=False) via the confirmation endpoint,
    or until the timeout expires (returns None → treated as cancel).

    Keyed by request_id, same as the SSE EventBus.
    """

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, bool] = {}

    def register(self, request_id: str) -> None:
        self._events[request_id] = asyncio.Event()
        print(f"[TRACE] confirmation_bus_register request_id={request_id}")

    async def wait_for_decision(
        self,
        request_id: str,
        timeout: float = 180.0,
    ) -> bool | None:
        """
        Block until resolve() is called or timeout expires.
        Returns True (continue), False (cancel), or None (timeout / not registered).
        Cleans up its own entries after returning.
        """
        event = self._events.get(request_id)
        if event is None:
            print(
                f"[TRACE] confirmation_bus_wait_skipped request_id={request_id} "
                f"reason=not_registered"
            )
            return None

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            decision = self._decisions.get(request_id)
            print(
                f"[TRACE] confirmation_bus_resolved request_id={request_id} "
                f"decision={decision}"
            )
            return decision
        except asyncio.TimeoutError:
            print(
                f"[TRACE] confirmation_bus_timeout request_id={request_id} "
                f"timeout_seconds={timeout}"
            )
            return None
        finally:
            self._events.pop(request_id, None)
            self._decisions.pop(request_id, None)

    def resolve(self, request_id: str, continue_grading: bool) -> bool:
        """
        Deliver the publisher's decision and unblock wait_for_decision().
        Returns True if there was a pending confirmation, False if none exists
        (e.g. the timeout already fired, or request_id is unknown).
        """
        event = self._events.get(request_id)
        if event is None:
            print(
                f"[TRACE] confirmation_bus_resolve_dropped request_id={request_id} "
                f"reason=no_pending_confirmation"
            )
            return False
        self._decisions[request_id] = continue_grading
        event.set()
        print(
            f"[TRACE] confirmation_bus_resolve request_id={request_id} "
            f"continue_grading={continue_grading}"
        )
        return True


confirmation_bus = ConfirmationBus()
