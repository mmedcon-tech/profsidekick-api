"""MYO'S Fertility: safety classification, KB chunking/metadata, transcripts, source filtering."""

import pytest

from app.services.fertility import doctor, knowledge, safety
from app.services.fertility.knowledge import KB_PATH, parse_kb, parse_transcript, window_segments


@pytest.mark.parametrize("text,role,category", [
    ("My partner gave me my first injection today, and I'm worried some medication leaked out. Should we inject more?", "patient", safety.MEDICATION),
    ("I think I only gave Nora half the injection. Can I give the rest?", "partner", safety.MEDICATION),
    ("I took the trigger injection late. What should I do now?", "patient", safety.MEDICATION),
    ("My nurse said my dose changed, but the app shows the old one.", "patient", safety.MEDICATION),
    ("I got a negative home test. Stop progesterone?", "patient", safety.MEDICATION),
    ("I missed yesterday's injection: should I double it?", "patient", safety.MEDICATION),
    ("I am embarrassed to ask, but my stomach is huge and I barely urinated today.", "patient", safety.EMERGENCY),
    ("I feel short of breath after retrieval.", "patient", safety.EMERGENCY),
    ("I feel faint and have heavy bleeding after retrieval.", "patient", safety.EMERGENCY),
    ("I have one-sided severe pelvic pain.", "patient", safety.EMERGENCY),
    ("I want to end my life", "patient", safety.CRISIS),
    ("Tell me Nora's hormone results.", "partner", safety.PARTNER_AUTH),
    ("What are my chances that IVF will work?", "patient", safety.PATIENT_DECISION),
    ("What should I eat or drink before anesthesia according to my clinic?", "patient", safety.CLINIC),
    ("Why am I feeling bloated during stimulation?", "patient", safety.GENERAL),
    ("What is progesterone doing?", "patient", safety.GENERAL),
    ("How can I help with injections?", "partner", safety.GENERAL),
])
def test_classify(text, role, category):
    assert safety.classify(text, role).category == category


def test_fixed_replies_never_advise_a_dose():
    for text in ("I only gave half the injection, can I give the rest?", "my trigger was late",
                 "stomach is swollen and I barely urinate"):
        r = safety.classify(text)
        assert r.deterministic and r.fixed_response
        low = r.fixed_response.lower()
        assert "give the rest" not in low and "take another" not in low
        assert r.escalation_offered and "simulated" in (r.escalation_label or "").lower()


def test_partner_private_request_only_for_partners():
    assert safety.classify("Tell me her hormone results", "patient").category != safety.PARTNER_AUTH


def test_kb_chunks_by_section_and_question_with_metadata():
    chunks = parse_kb(KB_PATH.read_text(encoding="utf-8"))
    patient_q = [c for c in chunks if c.meta["section"].startswith("5.")]
    partner_q = [c for c in chunks if c.meta["section"].startswith("6.")]
    assert len(patient_q) == 73 and len(partner_q) == 30
    assert all(c.meta["audience"] == "patient" for c in patient_q)
    assert all(c.meta["audience"] == "partner" for c in partner_q)
    assert len({c.meta["question_id"] for c in patient_q + partner_q}) == 103
    sections = {c.meta["section"].split(".")[0] for c in chunks}
    assert sections == {str(i) for i in range(1, 15)}
    required = {"document_id", "section", "question_id", "audience", "treatment_stage", "topic", "risk_level",
                "source_type", "clinic_id", "patient_id_if_applicable", "jurisdiction", "clinician_approver",
                "approval_status", "effective_at", "reviewed_at", "expires_at", "version", "citation_label",
                "escalation_route", "permitted_channels", "consent_scope"}
    assert all(required <= set(c.meta) for c in chunks)
    assert all(c.meta["approval_status"] == "demo_unreviewed" for c in chunks)
    demo = [c for c in chunks if c.meta["section"].startswith(("8.", "9."))]
    assert demo and all(c.meta["source_type"] == "synthetic_demo" for c in demo)
    trig = next(c for c in patient_q if "trigger injection late" in c.content)
    assert trig.meta["risk_level"] == "urgent" and trig.meta["escalation_route"]


def test_transcript_parsing_and_windows():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nCheck the pen label.\n\n00:00:05.000 --> 00:00:09.000\nAttach a new needle.\n\n00:01:30.000 --> 00:01:35.000\nDispose of the needle."
    segs = parse_transcript(vtt)
    assert [s["start"] for s in segs] == [1, 5, 90]
    wins = window_segments(segs)
    assert [w["start"] for w in wins] == [1, 90]
    assert parse_transcript("[0:10] Wash hands\n[1:02] Pinch skin")[1]["start"] == 62
    assert parse_transcript("just text")[0]["start"] == 0


def test_phase_two_only_allows_approved_sources(monkeypatch):
    base = {"approval_status": "demo_unreviewed", "audience": "both", "consent_scope": "public"}
    assert knowledge._permitted(base, "patient", knowledge.allowed_approval_statuses(1), "text")
    assert not knowledge._permitted(base, "patient", knowledge.allowed_approval_statuses(2), "text")
    monkeypatch.setenv("FERTILITY_KNOWLEDGE_PHASE", "2")
    assert knowledge.knowledge_phase() == 2


def test_source_filtering_respects_audience_and_patient_scope():
    statuses = knowledge.allowed_approval_statuses(1)
    assert not knowledge._permitted({"approval_status": "demo_unreviewed", "audience": "partner"}, "patient", statuses, "text")
    assert not knowledge._permitted({"approval_status": "demo_unreviewed", "audience": "both",
                                     "patient_id_if_applicable": "x"}, "patient", statuses, "text")
    assert not knowledge._permitted({"approval_status": "demo_unreviewed", "audience": "both",
                                     "consent_scope": "patient_only"}, "partner", statuses, "text")


def test_role_aware_suggested_questions():
    assert doctor.suggested_questions("patient")[0] == "Why am I feeling bloated during stimulation?"
    assert "How can I help with injections?" in doctor.suggested_questions("partner")
    staged = doctor.suggested_questions("partner", "trigger_retrieval")
    assert staged[0] == "How do I organize transport after sedation?"
    assert doctor.suggested_questions("unknown")[0] == doctor.SUGGESTED_QUESTIONS["patient"][0]


def test_source_only_fallback_skips_bare_questions():
    from app.services.fertility.consultation import _source_only_reply

    q = {"content": "Sec\nQ03: How?", "meta": {"question_id": "P-1"}}
    a = {"content": "Sec — Sub\nProgesterone supports the lining.", "meta": {}}
    assert _source_only_reply([q]) is None
    out = _source_only_reply([q, a])
    assert "Progesterone supports the lining." in out and "can't reach the answer service" in out


def test_internal_operating_sections_are_not_patient_answers():
    from app.services.fertility import knowledge as k

    chunks = k.parse_kb(k.KB_PATH.read_text(encoding="utf-8"))
    internal = {c.meta["section"].split(".")[0] for c in chunks if c.meta["consent_scope"] == "internal"}
    assert internal == {"1", "2", "3", "11", "12", "13"}
