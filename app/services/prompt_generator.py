"""
Generates a refined teaching persona prompt from an avatar's name, description,
and structured teaching preferences.  The output is stored in
PublisherAvatarProfile.refined_prompt and injected into sessions at runtime.
"""

from app.services.teaching_preference_mapper import (
    get_pace_description,
    get_questioning_description,
    get_formality_description,
    get_depth_description,
    get_encouragement_description,
    get_language_description,
)

_TEMPLATE = """\
You are an educational AI assistant representing this professor.

Avatar Description:
{avatar_description}

Teaching Pace:
{pace_description}

Questioning Style:
{questioning_description}

Communication Style:
{formality_description}

Explanation Depth:
{depth_description}

Encouragement:
{encouragement_description}

Language Complexity:
{language_description}

Always remain consistent with these teaching preferences throughout the session. \
Adapt explanations to the student's understanding while preserving the professor's \
teaching style. Prioritize learning, clarity, and conceptual understanding.\
"""


def generate_teaching_persona_prompt(
    *,
    avatar_name: str,
    avatar_description: str | None,
    teaching_pace: str | None = None,
    questioning_style: str | None = None,
    formality_level: str | None = None,
    depth_level: str | None = None,
    encouragement_level: str | None = None,
    language_level: str | None = None,
) -> str:
    description_text = avatar_description or f"An educational AI assistant named {avatar_name}."

    return _TEMPLATE.format(
        avatar_description  = description_text,
        pace_description    = get_pace_description(teaching_pace),
        questioning_description = get_questioning_description(questioning_style),
        formality_description   = get_formality_description(formality_level),
        depth_description       = get_depth_description(depth_level),
        encouragement_description = get_encouragement_description(encouragement_level),
        language_description    = get_language_description(language_level),
    )
