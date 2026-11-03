"""Shared check for the model-unavailable path: either a clearly matched, labelled clinic FAQ
quote, or a short message with the care-team handoff. Never a disguised or unlabelled answer."""
from app.services.care import guidance


def assert_labelled_fallback(result, text=None):
    text = text if text is not None else result["text"]
    assert "model" not in text.lower() and "unavailable" not in text.lower()
    if result["provenance"] == "source_quote":
        assert result["type"] == "education" and text.startswith(guidance.FALLBACK_LEAD)
        assert len(result["sources"]) == 1 and "[1]" in text
        return "faq"
    assert result["provenance"] == "clinic_configured" and result["type"] == "source_unavailable"
    assert result["handoff_offered"] and not result["sources"] and text == guidance.MODEL_DOWN_REPLY
    return "handoff"
