"""
Standard OpenAI Realtime API tool schemas for live session interactions.

These tool definitions are injected into the Realtime session so the avatar
can signal structured events (hand raise, session end, hint request, confusion
flag) that the frontend can intercept and handle without parsing free-form text.
"""

from typing import Any, Dict, List

RAISE_HAND: Dict[str, Any] = {
    "type": "function",
    "name": "raise_hand",
    "description": (
        "Signal that the student has raised their hand to ask a question or request "
        "attention. Call this when the student explicitly says they want to ask something "
        "or need help."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Brief description of why the student raised their hand.",
            }
        },
        "required": [],
    },
}

END_SESSION: Dict[str, Any] = {
    "type": "function",
    "name": "end_session",
    "description": (
        "Signal that the session should end. Call this when the student explicitly "
        "requests to end the session, or when all material has been covered and a "
        "natural closing point is reached."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One-sentence summary of what was covered in this session.",
            }
        },
        "required": [],
    },
}

REQUEST_HINT: Dict[str, Any] = {
    "type": "function",
    "name": "request_hint",
    "description": (
        "Signal that the student has requested a hint. Only call this when the session "
        "hint policy allows hints. The frontend uses this to track hint usage and apply "
        "any configured scoring deductions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The specific concept or step the student needs a hint on.",
            }
        },
        "required": ["topic"],
    },
}

FLAG_CONFUSION: Dict[str, Any] = {
    "type": "function",
    "name": "flag_confusion",
    "description": (
        "Signal that the student appears confused about a concept. Call this when the "
        "student expresses significant confusion or when their responses indicate a "
        "fundamental misunderstanding that should be logged for the publisher's review."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "concept": {
                "type": "string",
                "description": "The concept or topic the student is confused about.",
            },
            "severity": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Estimated severity of the confusion.",
            },
        },
        "required": ["concept"],
    },
}

# All standard session tools in injection order
SESSION_TOOLS: List[Dict[str, Any]] = [
    RAISE_HAND,
    END_SESSION,
    REQUEST_HINT,
    FLAG_CONFUSION,
]


def get_session_tools() -> List[Dict[str, Any]]:
    """Return the standard set of Realtime session tool schemas."""
    return SESSION_TOOLS
