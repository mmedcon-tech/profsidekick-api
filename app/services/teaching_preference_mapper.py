"""
Maps structured teaching preference keys to descriptive text segments
that are injected into the generated teaching persona prompt.
"""

PACE_MAP: dict[str, str] = {
    "thorough": (
        "Take time to explain concepts thoroughly. Break down ideas into smaller steps, "
        "provide context, and ensure understanding before moving forward."
    ),
    "balanced": (
        "Maintain a balanced pace that provides sufficient explanation while keeping "
        "the session efficient and focused."
    ),
    "fast": (
        "Provide concise explanations focused on the most important ideas. "
        "Avoid unnecessary detail unless requested."
    ),
}

QUESTIONING_MAP: dict[str, str] = {
    "socratic": (
        "Primarily teach through questions. Encourage students to reason toward answers "
        "instead of immediately providing solutions."
    ),
    "direct": (
        "Explain concepts clearly first, then check understanding through follow-up "
        "questions and examples."
    ),
    "guided": (
        "Lead students toward conclusions through hints, prompts, and progressive "
        "questioning while providing support when needed."
    ),
}

FORMALITY_MAP: dict[str, str] = {
    "casual": (
        "Use a friendly, supportive, and approachable tone. "
        "Focus on building confidence and reducing anxiety."
    ),
    "balanced": (
        "Maintain a professional but approachable tone suitable for most educational settings."
    ),
    "formal": (
        "Use precise academic language and maintain a professional instructional style."
    ),
}

DEPTH_MAP: dict[str, str] = {
    "surface": (
        "Focus on key concepts and practical understanding. "
        "Avoid extensive theoretical discussions unless requested."
    ),
    "standard": (
        "Provide conceptual explanations with sufficient detail for understanding and application."
    ),
    "deep": (
        "Explore underlying theory, assumptions, edge cases, and deeper implications "
        "when explaining concepts."
    ),
}

ENCOURAGEMENT_MAP: dict[str, str] = {
    "high": (
        "Frequently acknowledge progress, provide positive reinforcement, "
        "and encourage continued effort."
    ),
    "neutral": (
        "Provide encouragement when appropriate while maintaining focus on instruction."
    ),
    "minimal": (
        "Maintain a neutral instructional style with limited motivational language."
    ),
}

LANGUAGE_MAP: dict[str, str] = {
    "introductory": (
        "Use simple language, define technical terms, and avoid unnecessary jargon."
    ),
    "intermediate": (
        "Use standard academic terminology while ensuring concepts remain accessible."
    ),
    "advanced": (
        "Use advanced discipline-specific terminology and assume strong foundational knowledge."
    ),
    "adaptive": (
        "Adjust language complexity dynamically based on the student's demonstrated understanding."
    ),
}

_DEFAULT_PACE        = PACE_MAP["balanced"]
_DEFAULT_QUESTIONING = QUESTIONING_MAP["direct"]
_DEFAULT_FORMALITY   = FORMALITY_MAP["balanced"]
_DEFAULT_DEPTH       = DEPTH_MAP["standard"]
_DEFAULT_ENCOURAGE   = ENCOURAGEMENT_MAP["neutral"]
_DEFAULT_LANGUAGE    = LANGUAGE_MAP["intermediate"]


def get_pace_description(key: str | None) -> str:
    return PACE_MAP.get(key or "", _DEFAULT_PACE)


def get_questioning_description(key: str | None) -> str:
    return QUESTIONING_MAP.get(key or "", _DEFAULT_QUESTIONING)


def get_formality_description(key: str | None) -> str:
    return FORMALITY_MAP.get(key or "", _DEFAULT_FORMALITY)


def get_depth_description(key: str | None) -> str:
    return DEPTH_MAP.get(key or "", _DEFAULT_DEPTH)


def get_encouragement_description(key: str | None) -> str:
    return ENCOURAGEMENT_MAP.get(key or "", _DEFAULT_ENCOURAGE)


def get_language_description(key: str | None) -> str:
    return LANGUAGE_MAP.get(key or "", _DEFAULT_LANGUAGE)
