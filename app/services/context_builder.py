"""
Centralized prompt assembly service.

Single source of truth for how prompts are built — replaces scattered
string concatenation in prompt_builder.py and publisher_chat_service.py.

Two public functions:
  build_realtime_instructions() — for OpenAI Realtime API sessions
  build_chat_system_prompt()    — for publisher / subscriber text chat

Prompt hierarchy (realtime):
  1.  Core persona         (mode-resolved: teaching_prompt, examination_prompt, or conversation_prompt)
  1b. Teaching persona     ([TEACHING PERSONA] from PublisherAvatarProfile.refined_prompt)
  1c. Grounding policy     ([GROUNDING POLICY] default or caller-supplied)
  2.  Role context         (role selected at session creation)
  3.  Session behaviour    (rubric, hints, professor instructions)
  4.  Session summary      (from previous completed runs on this session)
  5.  Knowledge context    ([KNOWLEDGE CONTEXT] RAG-retrieved chunks)
  6.  Slide content        (Vision-extracted per-slide text)
  7.  Solution slides      (internal reference — never revealed)

Prompt hierarchy (chat):
  1. Template conversation_prompt  (from AvatarTemplateVersion, or legacy fallback)
  2. Role context
  3. Avatar configuration          (difficulty, rubrics, knowledge chunks, solutions)
  4. Session summary
  5. Slide content from session    (if a session_id was passed)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

GROUNDING_POLICY_DEFAULT = (
    "Respond only from the provided course materials and session context. "
    "If a question falls outside the provided materials, acknowledge the gap "
    "rather than drawing on external knowledge."
)

MATH_FORMATTING_INSTRUCTION = (
    "[MATH FORMATTING]\n"
    "When writing any mathematical notation, wrap it in LaTeX delimiters so it renders correctly: "
    "use $...$ for inline expressions (e.g., $x^2 + 1$) and $$...$$ for standalone/display equations "
    "(e.g., $$\\frac{d}{dx}x^2 = 2x$$). Never output LaTeX commands (\\frac, \\cdot, ^{}, _{}, etc.) "
    "without these delimiters."
)

# ── Legacy fallback (kept for avatars with no published version) ─────────────
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


# ─── helpers ────────────────────────────────────────────────────────────────

def _slide_block(slides: List[Any], prefix: str = "") -> str:
    lines = []
    for slide in slides:
        if isinstance(slide, dict):
            num = slide.get("slideNumber")
            title = slide.get("title", "")
            content = slide.get("content", "")
        else:
            num = getattr(slide, "slideNumber", None)
            title = getattr(slide, "title", "")
            content = getattr(slide, "content", "")
        if num is not None and content:
            lines.append(f"{prefix}Slide {num}: {title}\n{content}")
    return "\n\n".join(lines)


def _role_block(role_label: Optional[str], role_context: Optional[str]) -> Optional[str]:
    if not role_label:
        return None
    parts = [f"[ROLE]\nYou are speaking with: {role_label}."]
    if role_context and role_context.strip():
        parts.append(f"Adjust your behaviour accordingly:\n{role_context.strip()}")
    return "\n".join(parts)


def _extract_session_behaviour(assistant_parameters: Any) -> Dict:
    """Parse the structured JSONB stored in Session.assistant_parameters."""
    raw = ""
    if isinstance(assistant_parameters, dict):
        raw = assistant_parameters.get("instructions", "") or ""
    else:
        raw = getattr(assistant_parameters, "instructions", "") or ""

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {
                "editable": parsed.get("editable", "") or "",
                "sessionBehavior": parsed.get("sessionBehavior") or {},
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return {"editable": raw, "sessionBehavior": {}}


# ─── Realtime sessions ───────────────────────────────────────────────────────

EXAMINATION_REINFORCEMENT = """\
[Assessment Directive]
This session is operating in EXAMINATION MODE. Your primary function is assessment, not instruction.

Core rules for this session:
- Evaluate the student's reasoning, accuracy, and understanding based solely on what they demonstrate.
- Assess responses against the provided rubric and course materials. Do not award partial credit silently — probe further if a response is incomplete.
- Do not teach, explain concepts, or provide direct answers. If the student is wrong, ask targeted follow-up questions that guide self-correction without giving the answer away.
- Stay strictly within the scope of the submitted materials and role definition. Do not introduce external examples or frameworks.
- Maintain examiner neutrality: avoid affirmations ("great", "exactly") that imply correctness before you have evaluated the full response.
- Prioritise evidence-based assessment: every evaluation point must be traceable to the student's stated reasoning or submitted work."""


def _resolve_prompt_for_mode(
    session_mode: Optional[str],
    teaching_prompt: Optional[str],
    examination_prompt: Optional[str],
    conversation_prompt: Optional[str],
) -> Optional[str]:
    """
    Select the correct base persona prompt based on session_mode.

    Priority:
      examination  → examination_prompt → conversation_prompt (fallback)
      teaching     → teaching_prompt    → conversation_prompt (fallback)
      consultation → teaching_prompt    → conversation_prompt (fallback)
      None/unknown → conversation_prompt (backward compat)
    """
    mode = (session_mode or "teaching").lower()
    if mode == "examination":
        candidate = (examination_prompt or "").strip()
        return candidate if candidate else ((conversation_prompt or "").strip() or None)
    else:
        # teaching and consultation both use the teaching/conversation prompt as base
        candidate = (teaching_prompt or "").strip()
        return candidate if candidate else ((conversation_prompt or "").strip() or None)


def build_realtime_instructions(
    *,
    assistant_parameters: Any,
    slides: List[Any],
    solution_slides: Optional[List[Any]] = None,
    # Avatar / template context
    conversation_prompt: Optional[str] = None,
    teaching_prompt: Optional[str] = None,
    examination_prompt: Optional[str] = None,
    document_analysis_prompt: Optional[str] = None,
    role_label: Optional[str] = None,
    role_context: Optional[str] = None,
    # Session mode: 'teaching' | 'examination'
    session_mode: Optional[str] = None,
    # Prior run summary for this session
    session_summary: Optional[str] = None,
    # Long-term memories for this user+avatar
    memories: Optional[List[str]] = None,
    # Publisher-configured teaching persona (from PublisherAvatarProfile.refined_prompt)
    refined_prompt: Optional[str] = None,
    # RAG-retrieved knowledge context
    rag_context: Optional[str] = None,
    # Grounding policy injected after the core persona
    grounding_policy: str = GROUNDING_POLICY_DEFAULT,
    # Pre-resolved prompt from PromptResolutionService — takes priority over template fields
    resolved_system_prompt: Optional[str] = None,
    # Structured grading feedback from a prior autograder run (assessment sessions only)
    grading_feedback: Optional[dict] = None,
) -> str:
    """
    Assemble the complete instruction string sent to the OpenAI Realtime API.
    """
    sb_data = _extract_session_behaviour(assistant_parameters)
    sb: Dict = sb_data["sessionBehavior"]
    editable: str = sb_data["editable"]

    hint_policy: str = sb.get("hintPolicy", "NONE") or "NONE"
    rubric: List[Dict] = sb.get("rubric", []) if isinstance(sb.get("rubric"), list) else []
    session_instructions: str = (sb.get("sessionInstructions", "") or "").strip()

    is_examination = (session_mode or "teaching").lower() == "examination"
    is_consultation = (session_mode or "teaching").lower() == "consultation"

    parts: List[str] = []

    # 1. Core persona — PromptResolutionService result takes priority over template fields
    resolved = resolved_system_prompt or _resolve_prompt_for_mode(session_mode, teaching_prompt, examination_prompt, conversation_prompt)
    parts.append(resolved if resolved else EXAMINER_BASE_PROMPT)
    parts.append(MATH_FORMATTING_INSTRUCTION)

    # 1b. Publisher teaching persona (from refined_prompt in PublisherAvatarProfile)
    if refined_prompt and refined_prompt.strip():
        parts.append(f"[TEACHING PERSONA]\n{refined_prompt.strip()}")

    # 1c. Grounding policy
    if grounding_policy and grounding_policy.strip():
        parts.append(f"[GROUNDING POLICY]\n{grounding_policy.strip()}")

    # 2. Role context
    role_blk = _role_block(role_label, role_context)
    if role_blk:
        parts.append(role_blk)

    # 2b. Mode reinforcement
    if is_examination:
        parts.append(EXAMINATION_REINFORCEMENT)
    elif is_consultation:
        parts.append(
            "[CONSULTATION MODE BEHAVIOUR]\n"
            "You are acting as an expert consultant. Listen carefully to the user's question or "
            "problem, provide clear and actionable advice, and ask clarifying questions when needed. "
            "Avoid lecturing — focus on addressing the specific need the user presents."
        )

    # 3. Rubric
    if rubric:
        rubric_lines = "\n".join(
            f"- {r.get('criterion', '')}: {r.get('weight', 0)}%"
            for r in rubric if r.get("criterion")
        )
        if rubric_lines:
            parts.append(f"[Rubric]\n{rubric_lines}")

    # 4. Hint policy
    hint_allowed = "YES" if hint_policy != "NONE" else "NO"
    if hint_policy == "PENALIZED":
        hint_rule = "Penalized mode applies rubric-based deduction for each hint used"
    elif hint_policy == "FREE":
        hint_rule = "Free mode allows hints without any score impact"
    else:
        hint_rule = "Hints are not permitted in this session"
    parts.append(f"[Hint Policy]\nAllowed: {hint_allowed}\nMode: {hint_policy}\nRules:\n- {hint_rule}")

    # 5. Professor instructions
    if editable.strip():
        parts.append(f"[Professor Instructions]\n{editable.strip()}")
    if session_instructions:
        parts.append(f"[Session Instructions]\n{session_instructions}")

    # 6. Previous session summary
    if session_summary and session_summary.strip():
        parts.append(
            f"[Previous Session Summary]\n"
            f"This student has worked with this material before. Key observations:\n"
            f"{session_summary.strip()}"
        )

    # 7. Long-term memories
    if memories:
        mem_block = "\n".join(f"- {m}" for m in memories if m.strip())
        if mem_block:
            parts.append(f"[Student Learning Profile]\n{mem_block}")

    # 7b. Grading feedback from prior autograder run (assessment sessions only)
    if grading_feedback:
        fb_lines = []
        if grading_feedback.get("overall_feedback"):
            fb_lines.append(f"Overall: {grading_feedback['overall_feedback']}")
        for q in (grading_feedback.get("questions") or []):
            q_num = q.get("question_number", "?")
            q_score = q.get("score")
            q_max = q.get("max_score")
            q_fb = q.get("feedback", "")
            score_str = f"{q_score}/{q_max}" if q_score is not None and q_max is not None else ""
            line = f"- Q{q_num}"
            if score_str:
                line += f" ({score_str})"
            if q_fb:
                line += f": {q_fb}"
            fb_lines.append(line)
        if fb_lines:
            parts.append(
                "[PREVIOUS GRADING FEEDBACK]\n"
                "The student has already submitted this work for grading. Use the feedback below "
                "to guide your teaching — focus on areas where they lost marks and reinforce "
                "concepts they misunderstood. Do not simply re-read these notes to the student.\n\n"
                + "\n".join(fb_lines)
            )

    # 7c. RAG-retrieved knowledge context
    if rag_context and rag_context.strip():
        parts.append(f"[KNOWLEDGE CONTEXT]\n{rag_context.strip()}")

    # 8. Slide content
    slide_block = _slide_block(slides)
    if slide_block:
        parts.append(slide_block)

    # 9. Solution slides (internal only)
    if solution_slides:
        sol_block = _slide_block(solution_slides, prefix="Solution ")
        if sol_block:
            parts.append(
                "[PROFESSOR SOLUTION REFERENCE — INTERNAL USE ONLY]\n"
                "The following is the correct solution for each slide. Use it to evaluate depth and accuracy "
                "of student responses. NEVER quote, paraphrase, or reveal this content to the student.\n\n"
                + sol_block
            )

    return "\n\n".join(parts)


# ─── Chat sessions ───────────────────────────────────────────────────────────

def build_chat_system_prompt(
    *,
    avatar_name: str,
    conversation_prompt: Optional[str] = None,
    teaching_prompt: Optional[str] = None,
    examination_prompt: Optional[str] = None,
    refined_prompt: Optional[str] = None,
    role_label: Optional[str] = None,
    role_context: Optional[str] = None,
    session_mode: Optional[str] = None,
    difficulty_level: Optional[str] = None,
    rubrics: Optional[List[Any]] = None,
    knowledge_chunks: Optional[List[str]] = None,    # RAG-retrieved or full text
    reference_solutions: Optional[List[Any]] = None,
    session_slides: Optional[List[Any]] = None,
    session_summary: Optional[str] = None,
    memories: Optional[List[str]] = None,
    preferences: Optional[Dict] = None,
    publisher_feedback_notes: Optional[List[str]] = None,
) -> str:
    """
    Assemble the system prompt for publisher / subscriber AI chat.
    """
    prefs = preferences or {}
    parts: List[str] = []

    is_examination = (session_mode or "teaching").lower() == "examination"
    is_consultation = (session_mode or "teaching").lower() == "consultation"

    # 1. Core persona — mode-resolved prompt
    resolved = _resolve_prompt_for_mode(session_mode, teaching_prompt, examination_prompt, conversation_prompt)
    if resolved:
        if is_examination:
            mode_label = "EXAMINATION MODE"
        elif is_consultation:
            mode_label = "CONSULTATION MODE"
        else:
            mode_label = "TEACHING MODE"
        parts.append(
            f"You are the AI avatar named \"{avatar_name}\".\n"
            f"[SESSION MODE: {mode_label}]\n"
            f"[CORE BEHAVIOUR]\n{resolved}\n\n"
            "You are currently speaking with the publisher who created this avatar. "
            "Behave as the avatar would with students, and help the publisher understand "
            "how you will respond in live sessions."
        )
    else:
        parts.append(
            f"You are \"{avatar_name}\", an educational AI assistant. "
            "Help the publisher design and refine educational experiences."
        )
    parts.append(MATH_FORMATTING_INSTRUCTION)

    # 1b. Publisher-configured teaching persona (generated from teaching style preferences)
    if refined_prompt and refined_prompt.strip():
        parts.append(f"[TEACHING PERSONA]\n{refined_prompt.strip()}")

    # 2. Role context
    role_blk = _role_block(role_label, role_context)
    if role_blk:
        parts.append(role_blk)

    # 2b. Mode reinforcement
    if is_examination:
        parts.append(EXAMINATION_REINFORCEMENT)
    elif is_consultation:
        parts.append(
            "[CONSULTATION MODE BEHAVIOUR]\n"
            "You are acting as an expert consultant. Listen carefully to the user's question or "
            "problem, provide clear and actionable advice, and ask clarifying questions when needed. "
            "Avoid lecturing — focus on addressing the specific need the user presents."
        )

    # 3. Configuration
    difficulty = difficulty_level or prefs.get("preferred_difficulty", "")
    if difficulty:
        parts.append(f"Difficulty level: {difficulty}")

    # 4. Rubric
    if rubrics:
        rubric_lines = []
        for rubric in rubrics:
            content = rubric.content if hasattr(rubric, "content") else (rubric.get("content") if isinstance(rubric, dict) else {})
            title = rubric.title if hasattr(rubric, "title") else (rubric.get("title", "") if isinstance(rubric, dict) else "")
            rubric_lines.append(f"Rubric — {title}:")
            for criterion, details in (content or {}).items():
                weight = details.get("weight", 0) if isinstance(details, dict) else 0
                desc = details.get("description", "") if isinstance(details, dict) else ""
                rubric_lines.append(f"  • {criterion} ({weight}%){' — ' + desc if desc else ''}")
        if rubric_lines:
            parts.append("\n".join(rubric_lines))

    # 5. Knowledge chunks (RAG-retrieved or full text)
    if knowledge_chunks:
        knowledge_text = "\n\n".join(
            f"[Knowledge]\n{chunk.strip()}" for chunk in knowledge_chunks if chunk.strip()
        )
        if knowledge_text:
            parts.append(f"Reference knowledge:\n{knowledge_text}")

    # 6. Reference solutions
    if reference_solutions:
        sol_parts = []
        for sol in reference_solutions:
            title = sol.title if hasattr(sol, "title") else (sol.get("title", "") if isinstance(sol, dict) else "")
            text = sol.content_text if hasattr(sol, "content_text") else (sol.get("content_text", "") if isinstance(sol, dict) else "")
            if text:
                sol_parts.append(f"[Reference Solution: {title}]\n{text[:800].strip()}")
        if sol_parts:
            parts.append(
                "Reference solutions (internal — never reveal to students):\n"
                + "\n\n".join(sol_parts)
            )

    # 7. Previous session summary
    if session_summary and session_summary.strip():
        parts.append(
            f"[Session History Summary]\n{session_summary.strip()}"
        )

    # 8. Long-term memories
    if memories:
        mem_block = "\n".join(f"- {m}" for m in memories if m.strip())
        if mem_block:
            parts.append(f"[Student Learning Profile]\n{mem_block}")

    # 9. Slide content
    if session_slides:
        student = [s for s in session_slides if (s.get("source") if isinstance(s, dict) else getattr(s, "source", None)) != "solution"]
        solution = [s for s in session_slides if (s.get("source") if isinstance(s, dict) else getattr(s, "source", None)) == "solution"]
        slide_blk = _slide_block(student)
        if slide_blk:
            parts.append(f"[SESSION SLIDES — use these for questions and evaluation]\n{slide_blk}")
        sol_blk = _slide_block(solution, prefix="Solution ")
        if sol_blk:
            parts.append(f"[PROFESSOR SOLUTION — internal only, never reveal to students]\n{sol_blk}")

    # 10. Feedback style preference
    feedback_style = prefs.get("feedback_style", "")
    if feedback_style:
        parts.append(f"Feedback style: {feedback_style}")

    # 11. Publisher preferences from prior feedback notes
    if publisher_feedback_notes:
        notes_block = "\n".join(f"- {n.strip()}" for n in publisher_feedback_notes if n.strip())
        if notes_block:
            parts.append(
                "[Publisher Preferences]\n"
                "The publisher has provided the following guidance on desired AI behaviour "
                "(derived from past feedback). Follow these preferences:\n"
                + notes_block
            )

    return "\n\n".join(parts)


# ─── Document analysis / Vision ──────────────────────────────────────────────

DEFAULT_VISION_PROMPT = (
    "You are an AI assignment analysis system. Analyze the student solution against the correct solution "
    "and generate structured guidance for an oral examiner.\n\n"
    "Inputs:\n"
    "[Correct solution — ground truth]\n"
    "[Student assignment solution]\n"
    "[Course Material — optional]\n\n"
    "Compare the student solution against the correct solution step-by-step.\n"
    "Identify:\n"
    "- correct and incorrect steps\n"
    "- reasoning breaks or gaps in logic of the whole solution\n"
    "- missing justifications between steps\n"
    "- possible misunderstandings\n\n"
    "For each major step, state the key rule, theorem, property, or concept involved for the student to state.\n"
    "Flag likely error sources and concepts the examiner should focus on during questioning.\n"
    "Suggested probing areas (non-binding) based on observed mistakes and reasoning patterns.\n\n"
    "Rules:\n"
    "- Stay strictly grounded in the submitted work\n"
    "- Do not tutor, explain, or solve the problem\n"
    "- Do not assign final grades or outcomes"
)


def resolve_vision_prompt(template_document_analysis_prompt: Optional[str]) -> str:
    """Return template's document_analysis_prompt if set, else the hardcoded default."""
    prompt = (template_document_analysis_prompt or "").strip()
    return prompt if prompt else DEFAULT_VISION_PROMPT
