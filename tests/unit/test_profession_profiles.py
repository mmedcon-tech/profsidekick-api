"""Profession-aware avatar instructions: each field behaves differently, education is unchanged."""

import json
from types import SimpleNamespace

import pytest

from app.services.context_builder import (
    EXAMINATION_REINFORCEMENT,
    EXAMINER_BASE_PROMPT,
    TEACHING_REINFORCEMENT,
    build_chat_system_prompt,
    build_realtime_instructions,
)
from app.services.profession_profiles import (
    PROFESSION_KEYS,
    get_prompt_profile,
    profession_from_category,
    resolve_avatar_profession,
)

AP = {
    "instructions": json.dumps(
        {
            "editable": "Focus on chapter 2",
            "sessionBehavior": {
                "hintPolicy": "FREE",
                "rubric": [{"criterion": "Clarity", "weight": 50}],
            },
        }
    )
}
SLIDES = [{"slideNumber": 1, "title": "Intro", "content": "Hello"}]


def _realtime(profession=None, mode="teaching", **kw):
    return build_realtime_instructions(
        assistant_parameters=AP,
        slides=SLIDES,
        session_mode=mode,
        session_summary="did well",
        memories=["likes examples"],
        profession=profession,
        **kw,
    )


# ── resolution ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "category,expected",
    [
        ("Medical", "healthcare"),
        ("Healthcare", "healthcare"),
        ("Legal", "legal"),
        ("Business & Consulting", "business"),
        ("Mathematics", "education"),
        ("Law Enforcement", None),
        ("Government", None),
        ("General", "general"),
        (" personal ", "general"),
        ("General Knowledge", None),
        ("General Science", "education"),
        (None, None),
        ("", None),
    ],
)
def test_profession_from_category(category, expected):
    assert profession_from_category(category) == expected


def test_resolve_prefers_explicit_avatar_profession():
    avatar = SimpleNamespace(
        profession="legal", template=SimpleNamespace(category="Medical")
    )
    assert resolve_avatar_profession(avatar) == "legal"


def test_resolve_uses_template_category_then_education():
    assert (
        resolve_avatar_profession(
            SimpleNamespace(template=SimpleNamespace(category="Clinic"))
        )
        == "healthcare"
    )
    assert (
        resolve_avatar_profession(
            SimpleNamespace(template=SimpleNamespace(category="Other"))
        )
        == "education"
    )
    assert resolve_avatar_profession(SimpleNamespace(template=None)) == "education"
    assert resolve_avatar_profession(None) == "education"


def test_resolve_ignores_unknown_profession_values():
    avatar = SimpleNamespace(
        profession="astronaut", template=SimpleNamespace(category="Legal")
    )
    assert resolve_avatar_profession(avatar) == "legal"


def test_unknown_profession_key_falls_back_to_education():
    assert get_prompt_profile("astronaut").key == "education"
    assert get_prompt_profile(None).key == "education"


# ── education is unchanged ──────────────────────────────────────────────────


def test_education_is_the_default():
    assert _realtime(None) == _realtime("education")
    assert build_chat_system_prompt(
        avatar_name="A", conversation_prompt="P"
    ) == build_chat_system_prompt(
        avatar_name="A", conversation_prompt="P", profession="education"
    )


def test_education_realtime_keeps_professor_wording():
    text = _realtime("education")
    assert TEACHING_REINFORCEMENT in text
    assert "[Professor Instructions]\nFocus on chapter 2" in text
    assert "This student has worked with this material before." in text
    assert "[Student Learning Profile]" in text
    assert "[Hint Policy]" in text
    assert EXAMINATION_REINFORCEMENT in _realtime("education", mode="examination")


def test_education_without_template_prompt_uses_examiner_prompt():
    assert _realtime("education").startswith(EXAMINER_BASE_PROMPT)


# ── each profession is treated differently ─────────────────────────────────


@pytest.mark.parametrize("profession", [k for k in PROFESSION_KEYS if k != "education"])
def test_non_education_avatars_are_never_told_they_are_professors(profession):
    for mode in ("teaching", "examination"):
        realtime = _realtime(profession, mode=mode).lower()
        chat = build_chat_system_prompt(
            avatar_name="A", session_mode=mode, memories=["m"], profession=profession
        ).lower()
        for text in (realtime, chat):
            assert "professor" not in text
            assert "student" not in text
            assert "lesson" not in text


@pytest.mark.parametrize("profession", [k for k in PROFESSION_KEYS if k != "education"])
def test_non_education_avatars_disclose_they_are_ai(profession):
    assert "you are an ai avatar, not the real person" in _realtime(profession).lower()


def test_healthcare_avatar_does_not_diagnose_and_escalates_emergencies():
    text = _realtime("healthcare")
    assert "[Consultation Directive]" in text
    assert "Do not diagnose, prescribe" in text
    assert "local emergency services" in text
    assert "[Clinician Instructions]\nFocus on chapter 2" in text
    assert "This patient has worked with this material before." in text
    assert "[Patient Profile]" in text


def test_healthcare_examination_mode_still_runs_as_consultation():
    text = _realtime("healthcare", mode="examination")
    assert "[Consultation Directive]" in text
    assert "[Assessment Directive]" not in text
    assert "[Hint Policy]" not in text


def test_legal_avatar_gives_information_not_advice():
    text = _realtime("legal")
    assert "[Client Meeting Directive]" in text
    assert "Do not give legal advice" in text
    assert "lawyer–client relationship" in text
    assert "[Lawyer Instructions]" in text


def test_business_avatar_can_assess_against_a_scorecard():
    standard = _realtime("business")
    assessing = _realtime("business", mode="examination")
    assert "[Advisory Directive]" in standard and "[Hint Policy]" not in standard
    assert "scorecard" in assessing and "[Hint Policy]" in assessing


def test_general_avatar_speaks_for_its_creator():
    text = _realtime("general")
    assert "[Conversation Directive]" in text
    assert text.startswith(
        "You are an AI avatar representing the person who created you."
    )
    assert "[Creator Instructions]" in text


def test_template_prompt_still_wins_over_profession_base_prompt():
    text = _realtime("healthcare", teaching_prompt="TEMPLATE PERSONA")
    assert text.startswith("TEMPLATE PERSONA")


def test_chat_preview_names_the_right_audience():
    chat = build_chat_system_prompt(
        avatar_name="Dr A", conversation_prompt="P", profession="healthcare"
    )
    assert "[SESSION MODE: CONSULTATION MODE]" in chat
    assert "Behave as the avatar would with patients" in chat
    fallback = build_chat_system_prompt(avatar_name="Dr A", profession="legal")
    assert fallback.startswith('You are "Dr A", the AI avatar of a legal professional.')
