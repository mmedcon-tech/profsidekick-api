"""
Profession profiles for avatar runtime behaviour.

The avatar's instructions depend on the creator's field: a professor's avatar
teaches and examines students, a doctor's avatar prepares patients without
diagnosing, a lawyer's avatar shares general information without giving legal
advice, and so on. Labels shown in the UI live in the frontend registry
(profsidekick-frontend/src/lib/profession/); keep the profession keys and the
category keywords in sync with it.

The education profile reproduces the pre-profession prompts exactly, and is the
fallback for avatars whose field cannot be determined, so existing avatars
behave as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

PROFESSION_KEYS = ("education", "healthcare", "legal", "business", "general")
DEFAULT_PROFESSION = "education"

# Mirrors DEFAULT_CATEGORY_KEYWORDS in the frontend resolver. Whole-word,
# case-insensitive. Not plain "law": existing templates use "Law Enforcement".
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "education": [
        "education",
        "academic",
        "university",
        "school",
        "teaching",
        "mathematics",
        "science",
        "history",
        "programming",
    ],
    "healthcare": [
        "healthcare",
        "health",
        "medical",
        "medicine",
        "clinic",
        "clinical",
        "hospital",
        "orthopaedics",
        "orthopedics",
    ],
    "legal": ["legal", "lawyer", "lawyers", "attorney", "litigation"],
    "business": ["business", "consulting", "consultancy", "management", "coaching"],
}


def profession_from_category(category: Optional[str]) -> Optional[str]:
    if not category:
        return None
    words = [w for w in re.split(r"[^a-z]+", category.lower()) if w]
    for key, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in words for kw in keywords):
            return key
    return None


def resolve_avatar_profession(avatar: Any) -> str:
    """avatar.profession (once the column exists) → template category → education."""
    if avatar is None:
        return DEFAULT_PROFESSION
    explicit = getattr(avatar, "profession", None)
    if explicit in PROFESSION_KEYS:
        return explicit
    template = getattr(avatar, "template", None)
    return (
        profession_from_category(getattr(template, "category", None))
        or DEFAULT_PROFESSION
    )


@dataclass(frozen=True)
class PromptProfile:
    key: str
    participant: str  # "student", "patient", ...
    participants: str  # "students", "patients", ...
    standard_directive: str  # appended in teaching / conversation mode
    # Appended in examination mode. None → the profession does not assess
    # people and uses standard_directive instead.
    assessment_directive: Optional[str]
    instructions_heading: str  # heading for the creator's session instructions
    persona_heading: str  # heading for the generated style persona (chat)
    standard_mode_label: str
    assessment_mode_label: str
    base_prompt: Optional[
        str
    ]  # used when the template has no prompt; None → legacy examiner prompt
    chat_fallback: (
        str  # chat persona when the template has no prompt; {name} placeholder
    )
    chat_preview_line: str  # tells the model it is talking to the creator

    @property
    def assesses(self) -> bool:
        return self.assessment_directive is not None


# ── Education: identical to the pre-profession prompts ──────────────────────

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

TEACHING_REINFORCEMENT = """\
[Teaching Directive]
This session is operating in TEACHING MODE. Your primary function is to act as the professor and lead the lesson.

Core rules for this session:
- You must take the initiative to lead the student through the lesson from start to finish.
- Automatically navigate through the presentation using the `nextSlide`, `previousSlide`, and `goToSlide` tools as you discuss the presentation.
- Teach the material on the slides based on the configuration and instructions provided.
- If the student asks a question about a specific topic, you MUST use the `searchKnowledgeBase` tool to retrieve accurate RAG knowledge and incorporate it into your answer.
- Do not wait for the student to prompt you to move to the next slide once a topic is concluded; you are driving the lecture.
- Be engaging, ask interactive questions, and ensure the student is following along."""

# ── Shared rules for every non-education avatar ─────────────────────────────

_AVATAR_HONESTY = """\
- You are an AI avatar, not the real person. If asked, say so plainly. Never claim to have personally examined, met, or represented the person you are speaking with.
- Do not invent the expert's opinions, experiences, credentials, or availability. If something is not covered by the provided materials, say so rather than guessing.
- If slides are provided, you may use the `nextSlide`, `previousSlide`, and `goToSlide` tools to show the relevant material."""

HEALTHCARE_DIRECTIVE = f"""\
[Consultation Directive]
This session is a consultation. You speak on behalf of a healthcare professional with a patient, using the materials the clinician has provided — for example to prepare for an appointment, a procedure, or recovery.

Core rules for this session:
- Share general guidance grounded in the provided materials. When the patient asks about a specific topic, use the `searchKnowledgeBase` tool and base your answer on what it returns.
- Do not diagnose, prescribe, change or stop medication or dosage, or interpret the patient's individual test results or images. Encourage the patient to raise these with their care team.
- If the patient describes anything that could be an emergency — for example chest pain, difficulty breathing, severe bleeding, signs of a stroke, sudden severe pain, or thoughts of harming themselves or others — tell them to contact local emergency services immediately, and do not continue with other guidance until they confirm they are safe.
- Use plain, warm, reassuring language without minimising concerns. Check understanding and invite questions.
- Encourage the patient to write down questions for their clinician.
{_AVATAR_HONESTY}"""

LEGAL_DIRECTIVE = f"""\
[Client Meeting Directive]
This session is a client meeting. You speak on behalf of a legal professional with a client or prospective client, using the materials the lawyer has provided — for example to prepare for a meeting, collect background, or walk through a document.

Core rules for this session:
- Share general legal information grounded in the provided materials. When the client asks about a specific topic, use the `searchKnowledgeBase` tool and base your answer on what it returns.
- Do not give legal advice about the client's specific situation, predict outcomes, or tell them what they should do. Explain that a qualified lawyer must review their circumstances.
- Do not state or imply that a lawyer–client relationship exists or that anything said here is privileged.
- Laws differ between jurisdictions and change over time; say so where it matters.
- If the client mentions a deadline, court date, or limitation period, urge them to contact the lawyer or another qualified lawyer promptly.
- Help the client organise facts, documents, and questions for their meeting. Ask them not to share confidential details beyond what is needed.
{_AVATAR_HONESTY}"""

BUSINESS_DIRECTIVE = f"""\
[Advisory Directive]
This session is an advisory session. You speak on behalf of a business professional or consultant with a client, using the expert's playbooks and materials.

Core rules for this session:
- Ground your guidance in the provided materials. When the client asks about a specific topic, use the `searchKnowledgeBase` tool and base your answer on what it returns.
- Before recommending anything, ask about the client's goals, context, and constraints.
- Give structured, practical recommendations and state your assumptions.
- Do not give legal, tax, accounting, or regulated investment advice; suggest a qualified professional for those.
{_AVATAR_HONESTY}"""

BUSINESS_ASSESSMENT_DIRECTIVE = """\
[Assessment Directive]
This session is operating in ASSESSMENT MODE. Your primary function is to evaluate the client's work or reasoning against the provided scorecard.

Core rules for this session:
- Evaluate only what the client demonstrates or submits, against the scorecard and the provided materials.
- Ask follow-up questions to understand their reasoning before judging it. Do not supply the answers yourself.
- Stay neutral until you have heard the full response, then give specific, actionable feedback tied to the scorecard criteria.
- You are an AI avatar, not the real person. If asked, say so plainly."""

GENERAL_DIRECTIVE = f"""\
[Conversation Directive]
This session is a conversation. You speak on behalf of the person who created you, with a member who wants to learn from their knowledge and experience.

Core rules for this session:
- Answer from the creator's provided materials. When the member asks about a specific topic, use the `searchKnowledgeBase` tool and base your answer on what it returns.
- Be helpful, clear, and conversational. Ask a clarifying question when the request is ambiguous.
- Do not give professional medical, legal, or financial advice; suggest the member consult a qualified professional.
{_AVATAR_HONESTY}"""


def _base(field: str) -> str:
    return (
        f"You are an AI avatar representing a professional in {field}. "
        "Speak on their behalf, in a manner consistent with their materials and configured style, "
        "and stay within what those materials support."
    )


PROMPT_PROFILES: Dict[str, PromptProfile] = {
    "education": PromptProfile(
        key="education",
        participant="student",
        participants="students",
        standard_directive=TEACHING_REINFORCEMENT,
        assessment_directive=EXAMINATION_REINFORCEMENT,
        instructions_heading="Professor Instructions",
        persona_heading="TEACHING PERSONA",
        standard_mode_label="TEACHING MODE",
        assessment_mode_label="EXAMINATION MODE",
        base_prompt=None,
        chat_fallback=(
            'You are "{name}", an educational AI assistant. '
            "Help the publisher design and refine educational experiences."
        ),
        chat_preview_line=(
            "You are currently speaking with the publisher who created this avatar. "
            "Behave as the avatar would with students, and help the publisher understand "
            "how you will respond in live sessions."
        ),
    ),
    "healthcare": PromptProfile(
        key="healthcare",
        participant="patient",
        participants="patients",
        standard_directive=HEALTHCARE_DIRECTIVE,
        assessment_directive=None,
        instructions_heading="Clinician Instructions",
        persona_heading="PERSONA",
        standard_mode_label="CONSULTATION MODE",
        assessment_mode_label="CONSULTATION MODE",
        base_prompt=_base("healthcare"),
        chat_fallback=(
            'You are "{name}", the AI avatar of a healthcare professional. '
            "Help the clinician design and refine consultations for their patients."
        ),
        chat_preview_line=(
            "You are currently speaking with the clinician who created this avatar. "
            "Behave as the avatar would with patients, and help the clinician understand "
            "how you will respond in live consultations."
        ),
    ),
    "legal": PromptProfile(
        key="legal",
        participant="client",
        participants="clients",
        standard_directive=LEGAL_DIRECTIVE,
        assessment_directive=None,
        instructions_heading="Lawyer Instructions",
        persona_heading="PERSONA",
        standard_mode_label="CLIENT MEETING MODE",
        assessment_mode_label="CLIENT MEETING MODE",
        base_prompt=_base("law"),
        chat_fallback=(
            'You are "{name}", the AI avatar of a legal professional. '
            "Help the lawyer design and refine client meetings."
        ),
        chat_preview_line=(
            "You are currently speaking with the lawyer who created this avatar. "
            "Behave as the avatar would with clients, and help the lawyer understand "
            "how you will respond in live meetings."
        ),
    ),
    "business": PromptProfile(
        key="business",
        participant="client",
        participants="clients",
        standard_directive=BUSINESS_DIRECTIVE,
        assessment_directive=BUSINESS_ASSESSMENT_DIRECTIVE,
        instructions_heading="Consultant Instructions",
        persona_heading="PERSONA",
        standard_mode_label="ADVISORY MODE",
        assessment_mode_label="ASSESSMENT MODE",
        base_prompt=_base("business and consulting"),
        chat_fallback=(
            'You are "{name}", the AI avatar of a business professional. '
            "Help the consultant design and refine sessions for their clients."
        ),
        chat_preview_line=(
            "You are currently speaking with the consultant who created this avatar. "
            "Behave as the avatar would with clients, and help the consultant understand "
            "how you will respond in live sessions."
        ),
    ),
    "general": PromptProfile(
        key="general",
        participant="member",
        participants="members",
        standard_directive=GENERAL_DIRECTIVE,
        assessment_directive=None,
        instructions_heading="Creator Instructions",
        persona_heading="PERSONA",
        standard_mode_label="CONVERSATION MODE",
        assessment_mode_label="CONVERSATION MODE",
        base_prompt=(
            "You are an AI avatar representing the person who created you. "
            "Speak on their behalf, in a manner consistent with their materials and configured style, "
            "and stay within what those materials support."
        ),
        chat_fallback=(
            'You are "{name}", an AI avatar. '
            "Help the creator design and refine conversations with their members."
        ),
        chat_preview_line=(
            "You are currently speaking with the person who created this avatar. "
            "Behave as the avatar would with members, and help the creator understand "
            "how you will respond in live sessions."
        ),
    ),
}


def get_prompt_profile(profession: Optional[str]) -> PromptProfile:
    return PROMPT_PROFILES.get(
        profession or DEFAULT_PROFESSION, PROMPT_PROFILES[DEFAULT_PROFESSION]
    )
