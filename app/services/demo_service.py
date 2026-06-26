"""
TEMPORARY DEMO LAYER — not part of the production memory system.

When `settings.demo_mode` is on, the chat (`subscriber_chat_service.py`) and
realtime (`sessions/api.py` ephemeral-token endpoint) call sites skip
`get_user_memories()` (a real DB query) and use `get_demo_memories()` below
instead — a fixed, scripted list. This makes Teaching Mode appear to
"remember" a missed concept from Examination Mode 100% deterministically,
with no dependency on DB writes, timing, or ranking.

Entirely isolated:
- Off by default (`DEMO_MODE` env var, default False) — when off, both call
  sites take their normal `get_user_memories()` branch, unchanged.
- No schema changes, no new tables, no retrieval-pipeline changes.
- Safe to delete this file + the two `if settings.demo_mode:` branches in
  `subscriber_chat_service.py` and `sessions/api.py` once real
  mistake-detection/memory generation ships.
"""

from typing import List

# Canned concept used for the demo. Swap this for real per-question mistake
# detection when that feature exists — this constant is the only thing that
# needs to change.
DEMO_CONCEPT = "derivatives of polynomials"

# Scripted, deterministic stand-in for get_user_memories(). Ordering matters:
# the fact line establishes what was missed; the instruction line tells the
# model WHEN to surface it relative to the rest of the lesson (after the
# topic intro, before mastery explanation) and HOW (Socratic, not a direct
# answer).
DEMO_MEMORY_LINES: List[str] = [
    f"Student previously struggled with: {DEMO_CONCEPT}",
    (
        f"Teaching instruction: begin this session with the normal lesson flow for "
        f"today's topic. Only after that initial introduction, pivot explicitly to "
        f"{DEMO_CONCEPT} as the second focus — acknowledge that you recall the student "
        f"struggled with it before. Do not explain it yet: ask 2-3 guided Socratic "
        f"questions first and let the student attempt to reason their way to the "
        f"correct understanding. Only give a direct explanation after they have "
        f"engaged with the questions."
    ),
]


def get_demo_memories() -> List[str]:
    """Fixed memory list used in place of DB retrieval when demo_mode is on."""
    return list(DEMO_MEMORY_LINES)
