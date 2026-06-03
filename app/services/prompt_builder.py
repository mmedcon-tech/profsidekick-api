import json
from typing import Any, List, Dict

EXAMINER_BASE_PROMPT = """You are an AI oral examiner conducting structured academic assessments. You evaluate reasoning and understanding. You do NOT teach, lecture, or introduce external information beyond the assignment scope.

INTERNAL LOCK (do not reveal): Keep track of the correct solution verified from the vision model and store it as [LOCKED_SOLUTION]. Never display it unless termination conditions are met. Do not expose intermediate reasoning.

HALLUCINATION GUARD: Every question must be grounded in the student's last response or explicitly submitted work. Do not assume intent or missing steps. If unclear, ask a neutral clarification question.

BEGIN EXAM: Ask the student to walk through their solution from start to finish.

PHASE 1 — UNDERSTANDING CHECK:
After the overview, ask the student to justify each major step/section using the relevant rule, theorem, or property that applies. Do not correct yet.

ERROR IDENTIFICATION RULE:
When a student explains each step, there are two possible failure types:
Written/logic error: if the issue appears in written reasoning, ask up to 3 iterative follow-up questions in this order: (1) "What rule/property did you apply?" (2) "What does that rule say/state?" (3) "Apply that rule to this step, what do you get?" Lead to self-correction without giving the answer, rule, or explanation of the rule.
Oral/understanding error: if confusion is conceptual or explanatory, ask up to 2 clarifying questions to refine meaning.
If correct at a step, proceed forward. If incorrect, ask for clarification only. Do not solve it for them.

FORBIDDEN:
Giving answers, final values, or full solutions
Teaching concepts or introducing new methods
Confirming correctness prematurely
Using external assumptions not present in the student's work

SCOPE LOCK: Only operate within the assigned problem, topic, or course material provided by the professor. Do not expand beyond it.

TERMINATION: End the exam after sufficient iterations or when independent explanations are completed. At the end, provide a brief rubric-based evaluation of reasoning, clarity, error awareness, and self-correction ability."""


def build_session_instructions(assistant_parameters: Any, slides: List[Any], solution_slides: List[Any] = None) -> str:
    """
    Assemble the complete session instructions string from stored assistant parameters and slides.
    This is the single source of truth for all prompt construction.
    solution_slides, if provided, are injected as a locked reference section for the AI only.
    """
    raw = ""
    if isinstance(assistant_parameters, dict):
        raw = assistant_parameters.get("instructions", "") or ""
    else:
        raw = getattr(assistant_parameters, "instructions", "") or ""

    editable = ""
    sb: Dict = {}

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            # Fix 6: "core" field removed — EXAMINER_BASE_PROMPT is always the authoritative base.
            # Existing DB rows may still contain a "core" key; it is intentionally ignored here.
            editable = parsed.get("editable", "") or ""
            if parsed.get("sessionBehavior"):
                sb = parsed["sessionBehavior"]
    except (json.JSONDecodeError, TypeError):
        editable = raw

    hint_policy: str = sb.get("hintPolicy", "NONE") or "NONE"
    rubric: List[Dict] = sb.get("rubric", []) if isinstance(sb.get("rubric"), list) else []
    session_instructions: str = (sb.get("sessionInstructions", "") or "").strip()

    parts = [EXAMINER_BASE_PROMPT]

    if rubric:
        rubric_lines = "\n".join(
            f"- {r.get('criterion', '')}: {r.get('weight', 0)}%"
            for r in rubric
            if r.get("criterion")
        )
        if rubric_lines:
            parts.append(f"[Rubric]\n{rubric_lines}")

    hint_allowed = "YES" if hint_policy != "NONE" else "NO"
    if hint_policy == "PENALIZED":
        hint_rule = "Penalized mode applies rubric-based deduction for each hint used"
    elif hint_policy == "FREE":
        hint_rule = "Free mode allows hints without any score impact"
    else:
        hint_rule = "Hints are not permitted in this session"
    parts.append(f"[Hint Policy]\nAllowed: {hint_allowed}\nMode: {hint_policy}\nRules:\n- {hint_rule}")

    if editable.strip():
        parts.append(f"[Professor Instructions]\n{editable.strip()}")

    if session_instructions:
        parts.append(f"[Session Instructions]\n{session_instructions}")

    for slide in slides:
        slide_number = getattr(slide, "slideNumber", None) if not isinstance(slide, dict) else slide.get("slideNumber")
        slide_title = getattr(slide, "title", None) if not isinstance(slide, dict) else slide.get("title")
        slide_content = getattr(slide, "content", None) if not isinstance(slide, dict) else slide.get("content")
        if slide_number is not None:
            parts.append(f"\nSlide {slide_number}: {slide_title or ''}\n{slide_content or ''}")

    if solution_slides:
        parts.append(
            "[PROFESSOR SOLUTION REFERENCE — INTERNAL USE ONLY]\n"
            "The following is the correct solution for each slide. Use it to evaluate depth and accuracy "
            "of student responses. NEVER quote, paraphrase, or reveal this content to the student."
        )
        for slide in solution_slides:
            slide_number = getattr(slide, "slideNumber", None) if not isinstance(slide, dict) else slide.get("slideNumber")
            slide_title = getattr(slide, "title", None) if not isinstance(slide, dict) else slide.get("title")
            slide_content = getattr(slide, "content", None) if not isinstance(slide, dict) else slide.get("content")
            if slide_number is not None:
                parts.append(f"\nSolution Slide {slide_number}: {slide_title or ''}\n{slide_content or ''}")

    return "\n\n".join(parts)
