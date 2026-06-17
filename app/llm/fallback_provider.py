from __future__ import annotations

import time
from datetime import datetime, timezone

from app.llm.errors import FatalError, RetryableError
from app.llm.event_bus import event_bus
from app.llm.provider import GradingResult, LLMProvider, StudentFiles


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _evt(event_type: str, request_id: str, provider_name: str, **extra) -> dict:
    return {
        "event": event_type,
        "request_id": request_id,
        "provider": provider_name,
        "timestamp": _now(),
        **extra,
    }


class FallbackProvider:
    """
    Routes a grading request through an ordered list of providers.

    For each provider:
      - RetryableError → retry up to provider.max_attempts times, then skip.
      - FatalError     → skip immediately (no retry).

    Returns the first successful GradingResult.
    Raises RuntimeError if every provider is exhausted.
    """

    def __init__(self, providers: list[LLMProvider]):
        self._providers = providers

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    async def grade(
        self,
        student_files: StudentFiles,
        request_id: str | None = None,
    ) -> GradingResult:
        t_chain_start = time.monotonic()
        last_error: Exception | None = None
        prev_provider_name: str | None = None
        providers_tried: list[dict] = []

        rid = request_id or "no-sse"
        print(
            f"[TRACE] request_id={rid} START fallback_chain "
            f"providers={self.provider_names}"
        )

        for provider in self._providers:
            # Emit fallback_switch when transitioning from a previously-failed provider.
            if prev_provider_name is not None:
                print(
                    f"[TRACE] request_id={rid} fallback_switch "
                    f"from={prev_provider_name} to={provider.name}"
                )
                if request_id:
                    await event_bus.publish(
                        request_id,
                        _evt(
                            "fallback_switch",
                            request_id,
                            provider.name,
                            **{"from": prev_provider_name, "to": provider.name},
                        ),
                    )

            t_provider_start = time.monotonic()
            attempts_made = 0
            max_att = provider.max_attempts
            provider_last_error: str = ""

            for attempt in range(1, max_att + 1):
                attempts_made = attempt
                print(
                    f"[TRACE] request_id={rid} provider_start "
                    f"name={provider.name} attempt={attempt}/{max_att}"
                )

                if request_id and attempt == 1:
                    await event_bus.publish(
                        request_id,
                        _evt("provider_started", request_id, provider.name, attempt=1),
                    )

                try:
                    result = await provider.grade(student_files)
                    duration_ms = _ms(t_provider_start)
                    print(
                        f"[TRACE] request_id={rid} provider_success "
                        f"name={provider.name} attempt={attempt} duration_ms={duration_ms}"
                    )
                    if request_id:
                        await event_bus.publish(
                            request_id,
                            _evt("provider_success", request_id, provider.name, attempt=attempt),
                        )

                    total_ms = _ms(t_chain_start)
                    providers_tried.append({"name": provider.name, "status": "success", "attempts": attempt})
                    print(
                        f"[TRACE] request_id={rid} FINAL_SUMMARY "
                        f"total_duration_ms={total_ms} "
                        f"providers_tried={providers_tried} "
                        f"final_status=success "
                        f"winning_provider={provider.name} "
                        f"source={result.source}"
                    )
                    return result

                except RetryableError as exc:
                    provider_last_error = str(exc)
                    print(
                        f"[TRACE] request_id={rid} provider_retry "
                        f"name={provider.name} attempt={attempt}/{max_att} "
                        f"error={exc}"
                    )
                    last_error = exc
                    if request_id and attempt < max_att:
                        await event_bus.publish(
                            request_id,
                            _evt(
                                "provider_retry",
                                request_id,
                                provider.name,
                                attempt=attempt,
                                reason=str(exc),
                                max_attempts=max_att,
                            ),
                        )

                except FatalError as exc:
                    provider_last_error = str(exc)
                    print(
                        f"[TRACE] request_id={rid} provider_fatal "
                        f"name={provider.name} error={exc}"
                    )
                    last_error = exc
                    break  # no point retrying a fatal error on the same provider

            providers_tried.append({
                "name": provider.name,
                "status": "failed",
                "attempts": attempts_made,
                "last_error": provider_last_error,
            })
            if request_id:
                await event_bus.publish(
                    request_id,
                    _evt(
                        "provider_failed",
                        request_id,
                        provider.name,
                        attempts_made=attempts_made,
                        reason=str(last_error),
                    ),
                )
            prev_provider_name = provider.name

        total_ms = _ms(t_chain_start)
        print(
            f"[TRACE] request_id={rid} ALL_PROVIDERS_FAILED "
            f"last_error={last_error}"
        )
        print(
            f"[TRACE] request_id={rid} FINAL_SUMMARY "
            f"total_duration_ms={total_ms} "
            f"providers_tried={providers_tried} "
            f"final_status=failure "
            f"last_error={last_error}"
        )
        raise RuntimeError(
            f"All grading providers exhausted. Last error: {last_error}"
        )


# ---------------------------------------------------------------------------
# Lazy singleton — built once on first call, reused for the lifetime of the
# process.  Provider instances carry no mutable state so this is safe.
# ---------------------------------------------------------------------------

_instance: FallbackProvider | None = None


def get_fallback_provider() -> FallbackProvider:
    global _instance
    if _instance is not None:
        return _instance

    from app.config import settings
    from app.llm.gemini_provider import GeminiProvider
    from app.llm.openai_provider import OpenAIProvider

    providers: list[LLMProvider] = []

    # Pro key — uses Gemini Files API for static PDFs (cached URIs).
    pro_key = settings.gemini_pro_api_key or settings.gemini_api_key
    if pro_key:
        providers.append(
            GeminiProvider(pro_key, settings.gemini_model, use_file_cache=True)
        )

    # Free key — file-URI cache is shared when the Free key is the same Google project
    # as Pro (same key value).  If the keys differ, fall back to inline base64 so we
    # never send a URI that belongs to a different project.
    free_key = settings.gemini_free_api_key
    free_can_use_cache = bool(free_key and free_key == pro_key)
    if free_key:
        providers.append(
            GeminiProvider(
                free_key,
                settings.gemini_model,
                use_file_cache=free_can_use_cache,
            )
        )

    # Gemini Flash — same key as Free; inherits the same cache eligibility.
    if free_key:
        providers.append(
            GeminiProvider(
                free_key,
                settings.gemini_flash_model,
                use_file_cache=free_can_use_cache,
                tier="flash",
            )
        )

    # OpenAI — stateless vision provider, full input each request.  Single shot.
    if settings.openai_api_key:
        providers.append(OpenAIProvider(settings.openai_api_key))

    if not providers:
        raise RuntimeError(
            "No LLM providers configured. Set at least one of: "
            "GEMINI_PRO_API_KEY, GEMINI_FREE_API_KEY, OPENAI_API_KEY."
        )

    print(f"[TRACE] fallback_provider_initialized providers={[p.name for p in providers]}")
    _instance = FallbackProvider(providers)
    return _instance
