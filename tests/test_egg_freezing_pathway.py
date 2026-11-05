"""Social egg freezing pathway: FAQ inventory, seeded stages/items, stage-aware Ask MYOS, device guide,
partner access and care-team routing. Real Postgres; AI stubbed."""
import json
from pathlib import Path

import pytest

from app.database.models import CareContentItem, CareCourse, CareDeviceAssignment, CareProgram, User
from app.services.care import chat, content, seed_myos
from tests.test_care_platform import _as, stub_ai, world  # noqa: F401

FERT = "/api/care/p/myos-fertility-sf"
STAGES = ["explore", "find-clinic", "assessment", "stimulation", "first-injection", "retrieval", "storage", "using-later"]
INV = json.loads((Path(seed_myos.SEED_DIR) / "egg_freezing_faq.json").read_text(encoding="utf-8"))
FIELDS = {"key", "question", "answer", "stage", "topic", "content_class", "pathways", "source_title", "source_url",
          "review_status", "version", "effective_date"}


def test_inventory_entries_are_complete_and_pending_review():
    assert len(INV) >= 40 and len({e["key"] for e in INV}) == len(INV)
    for e in INV:
        assert FIELDS <= set(e), e["key"]
        assert e["stage"] in STAGES and e["answer"].strip() and e["source_url"].startswith("https://")
        assert e["review_status"] == "in_review"  # nothing imported as approved
        assert e["content_class"] in ("education", "clinic_specific", "individual")
        assert "social-egg-freezing" in e["pathways"]
    assert {e["stage"] for e in INV} == set(STAGES)


@pytest.fixture
def ef(world, stub_ai):  # noqa: F811
    db = world["db"]
    seed_myos.seed(db)
    users = {u.username: u for u in db.query(User).filter(User.username.in_(["nora", "leo", "sofia"]))}
    prog = db.query(CareProgram).filter_by(slug="egg-freezing").one()
    return {**world, "u": users, "prog": prog}


def test_seed_builds_eight_stages_and_in_review_faqs(ef):
    db, prog = ef["db"], ef["prog"]
    assert prog.name == "Social egg freezing"
    pub = [c.slug for c in db.query(CareCourse).filter_by(program_id=prog.id, status="published").order_by(CareCourse.position)]
    assert pub == STAGES
    items = db.query(CareContentItem).filter(CareContentItem.program_id == prog.id,
                                             CareContentItem.seed_key.like("egg-freezing:faq-%")).all()
    assert len(items) == len(INV)
    assert {i.status for i in items} == {"in_review"} and all(i.approved_at is None for i in items)
    assert all(i.source_url for i in items)


def test_synthetic_patient_has_confirmed_demo_device_guide(ef):
    db, prog = ef["db"], ef["prog"]
    d = db.query(CareDeviceAssignment).filter_by(program_id=prog.id, user_id=ef["u"]["nora"].id, revoked_at=None).one()
    guide = db.query(CareContentItem).filter_by(lineage_id=d.guide_lineage_id).first()
    assert d.is_demo and d.device == "FSH pen" and guide.title == "FSH pen"
    assert "synthetic" in ef["u"]["nora"].last_name


def test_stage_choice_is_validated(ef):
    db, prog = ef["db"], ef["prog"]
    assert chat._chosen_stage(db, prog, "storage") == "storage"
    assert chat._chosen_stage(db, prog, "freezing-and-storage") is None  # retired stage
    assert chat._chosen_stage(db, prog, "nope") is None


def test_storage_stage_ranks_storage_material_first(ef):
    db, prog = ef["db"], ef["prog"]
    courses = {c.id for c in db.query(CareCourse).filter_by(program_id=prog.id)}
    hits = content.retrieve(db, program_id=prog.id, clinic_id=prog.clinic_ref_id, visible_course_ids=courses,
                            audience="patient", query="How long can I store my eggs?", stage="storage")
    assert hits and hits[0]["title"] == "How long can I store my eggs?"


def test_ask_with_stage_answers_from_sources(ef):
    _as(ef["u"]["nora"])
    r = ef["client"].post(f"{FERT}/egg-freezing/messages",
                          json={"content": "What should I check before renewing storage?", "stage": "storage"})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["type"] == "education" and res["sources"]


def test_conflicting_instructions_reach_the_care_team(ef):
    _as(ef["u"]["nora"])
    r = ef["client"].post(f"{FERT}/egg-freezing/messages",
                          json={"content": "Two instructions show different doses for my FSH pen tonight. Which one is right?",
                                "stage": "first-injection"}).json()
    assert r["result"]["type"] != "education"
    assert r["result"].get("handoff_offered") or r["result"].get("handoff")


def test_partner_sees_shared_guides_not_conversations(ef):
    c = ef["client"]
    _as(ef["u"]["leo"])
    assert c.get(f"{FERT}/egg-freezing").status_code == 200
    assert c.post(f"{FERT}/egg-freezing/messages", json={"content": "hi"}).status_code in (403, 404)
