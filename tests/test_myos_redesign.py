"""MYOS redesign: seed from seed/*.json, pilot status rule, progesterone retrieval, model fallback,
first-run guide state, conversation history, supporter scope. Real Postgres; AI stubbed."""
import re
import uuid
from pathlib import Path

import pytest

from app.database.models import CareContentItem, CareProgram, Clinic, User
from app.services.care import chat, content, seed_myos
from tests.test_care_platform import _as, _user, stub_ai, world  # noqa: F401

FERT = "/api/care/p/myos-fertility-sf"


@pytest.fixture
def myos(world, stub_ai):  # noqa: F811
    db = world["db"]
    seed_myos.seed(db)
    users = {u.username: u for u in db.query(User).filter(User.username.in_(["sofia", "daniel", "ahmed", "publisher"]))}
    return {**world, "u": users}


def test_seed_is_idempotent_and_keeps_publisher_edits(myos):
    db = myos["db"]
    again = seed_myos.seed(db)
    assert again["created"] == 0
    item = db.query(CareContentItem).filter_by(seed_key="ivf-care:ivf-overview", status="in_review").one()
    assert item.source_url.startswith("https://www.hfea.gov.uk/") and item.reviewer == "Awaiting clinician"
    assert item.approved_sha256 and content.integrity.verify(item)
    edited = content.new_version(db, item, myos["u"]["publisher"], body=item.body + " Edited by the clinic.")
    db.commit()
    assert edited.edited_at is not None
    seed_myos.seed(db)
    latest = (db.query(CareContentItem).filter_by(lineage_id=item.lineage_id)
              .order_by(CareContentItem.version.desc()).first())
    assert latest.id == edited.id and "Edited by the clinic." in latest.body


def test_in_review_content_only_visible_in_pilot_workspaces(myos):
    db, c = myos["db"], myos["client"]
    _as(myos["u"]["sofia"])
    view = c.get(f"{FERT}/ivf-care").json()
    labels = {i["status_label"] for i in view["content"]}
    assert labels == {"In clinical review"}
    clinic = db.query(Clinic).filter_by(slug="myos-fertility-sf").one()
    clinic.is_pilot = False
    db.commit()
    try:
        assert c.get(f"{FERT}/ivf-care").json()["content"] == []
        prog = db.query(CareProgram).filter_by(slug="ivf-care").one()
        assert content.retrieve(db, program_id=prog.id, clinic_id=clinic.id, visible_course_ids=set(),
                                audience="patient", query="stimulation medication") == []
    finally:
        clinic.is_pilot = True
        db.commit()


def test_progesterone_question_ranks_progesterone_guide_first(myos):
    db = myos["db"]
    prog = db.query(CareProgram).filter_by(slug="ivf-medication-preparation").one()
    courses = {cc.id for cc in prog_courses(db, prog)}
    hits = content.retrieve(db, program_id=prog.id, clinic_id=prog.clinic_ref_id, visible_course_ids=courses,
                            audience="patient", query="How do I use my progesterone?")
    assert hits and hits[0]["title"] == "Progesterone"


def prog_courses(db, prog):
    from app.database.models import CareCourse
    return db.query(CareCourse).filter_by(program_id=prog.id).all()


def test_model_failure_retries_once_then_friendly_fallback(myos, monkeypatch):
    c = myos["client"]
    calls = []

    async def boom(messages):
        calls.append(1)
        raise RuntimeError("down")

    monkeypatch.setattr(chat, "_complete", boom)
    _as(myos["u"]["sofia"])
    r = c.post(f"{FERT}/ivf-care/messages", json={"content": "What happens during stimulation?"}).json()
    assert len(calls) == 2
    assert r["reply"]["content"].startswith(chat.FALLBACK_INTRO)
    assert r["result"]["sources"]


def test_first_run_guide_shows_once_and_can_be_reopened(myos):
    c = myos["client"]
    u = myos["u"]["sofia"]
    u.onboarding_completed_at = None
    myos["db"].commit()
    _as(u)
    s = c.get("/api/care/me/onboarding").json()
    assert s["show"] is True and s["kind"] == "patient"
    assert c.post("/api/care/me/onboarding", json={"action": "complete"}).json()["show"] is False
    assert c.get("/api/care/me/onboarding").json()["show"] is False
    assert c.post("/api/care/me/onboarding", json={"action": "reset"}).json()["show"] is True
    _as(myos["u"]["daniel"])
    assert c.get("/api/care/me/onboarding").json()["kind"] == "supporter"
    _as(myos["u"]["publisher"])
    assert c.get("/api/care/me/onboarding").json()["kind"] == "publisher"
    assert c.post("/api/care/me/onboarding", json={"action": "nope"}).status_code == 422


def test_history_lists_conversations_with_answered_count_and_requests(myos):
    c = myos["client"]
    _as(myos["u"]["sofia"])
    c.post(f"{FERT}/ivf-care/messages", json={"content": "What happens during stimulation?"})
    convs = c.get("/api/care/me/conversations").json()["conversations"]
    ivf = next(x for x in convs if x["program"]["slug"] == "ivf-care")
    assert ivf["answered_questions"] >= 1 and ivf["last_exchange"]["question"] == "What happens during stimulation?"
    med = next(x for x in convs if x["program"]["slug"] == "ivf-medication-preparation")
    assert any(rq["state"] == "waiting" for rq in med["requests"])


def test_supporter_cannot_open_conversations(myos):
    c = myos["client"]
    _as(myos["u"]["daniel"])
    assert c.get(f"{FERT}/ivf-medication-preparation").status_code == 200
    assert c.get(f"{FERT}/ivf-medication-preparation/consultation").status_code in (403, 404)
    assert c.get(f"{FERT}/ivf-care").status_code in (403, 404)


def test_seed_text_has_no_banned_strings():
    bad = re.compile(r"—|!|fictional|\(demo\)|MYO'S", re.I)
    for f in Path(seed_myos.SEED_DIR).glob("*.json"):
        hits = [m.group(0) for m in bad.finditer(f.read_text(encoding="utf-8"))]
        assert not hits, f"{f.name}: {hits}"


def test_seed_holds_exact_avery_first_message(myos):
    from app.database.models import DoctorPersona
    p = myos["db"].query(DoctorPersona).filter_by(slug="dr-avery").one()
    assert p.first_messages["en"].replace("{first_name}", "Sofia") == (
        "Hi Sofia, I'm Dr. Avery, an AI guide for MYOS Fertility Pilot. I explain your clinic's approved material "
        "on IVF and egg freezing. For anything about your own dose, results or symptoms, I'll help you reach your "
        "care team. What's on your mind?")


def test_hanging_model_falls_back_within_one_shared_budget(myos, monkeypatch):
    import asyncio
    import time as _t

    async def hang(messages):
        await asyncio.sleep(30)

    monkeypatch.setattr(chat, "_complete", hang)
    monkeypatch.setattr(chat, "LLM_TIMEOUT_S", 1.0)
    _as(myos["u"]["sofia"])
    t0 = _t.monotonic()
    r = myos["client"].post(f"{FERT}/ivf-care/messages", json={"content": "What happens during stimulation?"}).json()
    assert _t.monotonic() - t0 < 2.5
    assert r["reply"]["content"].startswith(chat.FALLBACK_INTRO)


def test_patient_can_change_own_stage_supporter_cannot(myos):
    c = myos["client"]
    _as(myos["u"]["sofia"])
    v = c.get(f"{FERT}/ivf-care").json()
    slugs = [x["slug"] for x in v["courses"]]
    assert v["stage"] in slugs
    assert c.put(f"{FERT}/ivf-care/stage", json={"stage": slugs[-1]}).json()["stage"] == slugs[-1]
    assert c.get(f"{FERT}/ivf-care").json()["stage"] == slugs[-1]
    assert c.put(f"{FERT}/ivf-care/stage", json={"stage": "nope"}).status_code == 422
    _as(myos["u"]["daniel"])
    assert c.put(f"{FERT}/ivf-medication-preparation/stage", json={"stage": "guides"}).status_code == 403
