"""General medication/lifestyle education is allowed; the patient's own doses, products,
schedule and treatment decisions stay routed to the care team."""
import pytest
from app.services.care import safety
from app.services.care.chat import device_question

GENERAL = [
    "What are the side effects of fertility injections?",
    "Why is the timing of the trigger injection so important?",
    "Should I stop smoking before IVF?",
    "Should I cut down on alcohol during treatment?",
    "Can I drink coffee during IVF?",
    "What are common side effects of progesterone injections?",
]
PERSONAL = [
    "How much should I inject?",
    "Should I skip my dose tonight?",
    "Should I stop my meds?",
    "Is my dose right?",
    "Should I stop taking my progesterone?",
    "Can I stop my injections and start smoking again?",
    "When should I inject my trigger?",
    "Should I increase my dose?",
]


def _personal(text):
    t = text.lower()
    m = safety._hits(t, safety._PERSONAL)
    return bool(m) and not safety._lifestyle_only(t)


@pytest.mark.parametrize("q", GENERAL)
def test_general_not_routed(q):
    assert not _personal(q)
    assert not device_question(q)


@pytest.mark.parametrize("q", PERSONAL)
def test_personal_still_blocked(q):
    assert _personal(q) or device_question(q), q


@pytest.mark.parametrize("q", ["How do I use my pen?", "How do I prepare the injection?", "What needle size is my pen?",
                               "Where do I inject?", "Which syringe do I use?"])
def test_device_handling_still_needs_verified_device(q):
    assert device_question(q)
