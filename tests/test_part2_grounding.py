"""Part 2: answers are grounded in the session's own clinic, stage and approved material."""
from types import SimpleNamespace

from app.services.care import chat, content
from tests.test_care_platform import _as, stub_ai, world  # noqa: F401
from tests.test_myos_redesign import FERT, myos  # noqa: F401
from tests.test_patient_text_hygiene import FACT, GUIDE, _chunk


def test_stage_tagged_items_only_reach_matching_stage():
    tagged = SimpleNamespace(applicability="stages: stimulation, egg_retrieval")
    general = SimpleNamespace(applicability=None)
    assert content.stage_applies(general, None) and content.stage_applies(general, "transfer")
    assert content.stage_applies(tagged, "Stimulation")
    assert not content.stage_applies(tagged, "transfer")
    assert not content.stage_applies(tagged, None)  # unknown stage never gets stage-specific material


def test_contact_block_lists_only_clinic_published_routes():
    clinic = SimpleNamespace(contact_routes=[
        {"key": "nurse", "label": "Nurse line", "detail": "+1 555 0100", "hours": "Mon-Fri 8-17"},
        {"key": "x"}, "junk"])
    b = chat.contact_block(clinic)
    assert "Nurse line: +1 555 0100 (hours: Mon-Fri 8-17)" in b and "junk" not in b
    assert chat.contact_block(SimpleNamespace(contact_routes=[])) == ""


def _patch(monkeypatch, chunks, reply="Answer [1]."):
    seen = {}

    def fake_retrieve(db, **kw):
        seen.update(kw)
        return list(chunks)
    monkeypatch.setattr(content, "retrieve", fake_retrieve)

    async def fake(messages):
        seen["system"] = messages[0]["content"]
        seen["n_messages"] = len(messages)
        if reply is None:
            raise RuntimeError("down")
        return reply
    monkeypatch.setattr(chat, "_complete", fake)
    return seen


def test_retrieval_scoped_by_session_clinic_program_audience_and_stage(myos, monkeypatch):
    seen = _patch(monkeypatch, [_chunk(1, FACT, "Progesterone after transfer")])
    _as(myos["u"]["sofia"])
    r = myos["client"].post(f"{FERT}/ivf-care/messages",
                            json={"content": "What does progesterone do?", "clinic_id": "other", "stage": "x"}).json()
    assert r["result"]["type"] == "education"
    assert seen["audience"] == "patient" and "stage" in seen
    assert seen["clinic_id"] is not None and seen["program_id"] is not None
    # the body cannot pick another clinic or stage: only the session-resolved values are passed
    assert seen["stage"] != "x"


def test_guidance_steers_but_is_not_a_source_and_rules_outrank_style(myos, monkeypatch):
    seen = _patch(monkeypatch, [_chunk(1, GUIDE, "Results guidance"), _chunk(2, FACT, "Progesterone after transfer")])
    _as(myos["u"]["sofia"])
    r = myos["client"].post(f"{FERT}/ivf-care/messages", json={"content": "What does progesterone do?"}).json()
    src_part = seen["system"].split("SOURCES:")[1]
    assert GUIDE not in src_part and [s["title"] for s in r["result"]["sources"]] == ["Progesterone after transfer"]
    assert "then the persona's style" in seen["system"]


def test_invented_citation_is_stripped(myos, monkeypatch):
    _patch(monkeypatch, [_chunk(1, FACT, "Progesterone after transfer")], reply="It supports the lining [1][7].")
    _as(myos["u"]["sofia"])
    r = myos["client"].post(f"{FERT}/ivf-care/messages", json={"content": "What does progesterone do?"}).json()
    assert "[7]" not in r["reply"]["content"] and [s["n"] for s in r["result"]["sources"]] == [1]


def test_faq_fallback_requires_approved_faq(myos, monkeypatch):
    faq = {**_chunk(1, "Progesterone supports the womb lining after transfer.", "Progesterone FAQ"), "kind": "faq",
           "status_label": "In clinical review"}
    _patch(monkeypatch, [faq], reply=None)
    _as(myos["u"]["sofia"])
    r = myos["client"].post(f"{FERT}/ivf-care/messages", json={"content": "What does progesterone do after transfer?"}).json()
    assert r["result"]["type"] == "source_unavailable" and r["result"]["handoff_offered"]
