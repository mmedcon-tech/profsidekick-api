"""IVF knowledge base pipeline: section chunking, BM25 specificity, source links, pilot pinning."""
import uuid

from app.database.models import CareContentItem, CareProgram, Clinic
from app.services.care import content, lexical
from tests.test_care_integrity import WM
from tests.test_care_platform import _as, _enroll, _user, stub_ai, world  # noqa: F401

STEPS = ("## The main steps of an IVF cycle\nStimulation, monitoring, a trigger injection, egg collection, "
         "fertilisation in the lab and embryo transfer.")
RETRIEVAL = ("## What happens during egg retrieval?\nEgg collection is a short procedure under sedation. A fine needle "
             "guided by ultrasound draws fluid from each follicle.\n\n## Recovery after egg collection\nCramping is common.")


def test_section_chunks_prefix_title_and_heading():
    parts = content.section_chunks("Egg retrieval", RETRIEVAL)
    assert len(parts) == 2
    assert parts[0].startswith("Egg retrieval: What happens during egg retrieval?") and "needle" in parts[0]
    assert parts[1].startswith("Egg retrieval: Recovery after egg collection")
    assert content.section_chunks("Plain", "one\n\ntwo") == content.chunk_text("Plain\n\none\n\ntwo")


def test_bm25_prefers_the_specific_passage_and_uses_synonyms():
    docs = ["What IVF is: The main steps\n" + STEPS.split("\n", 1)[1]] + content.section_chunks("Egg collection", RETRIEVAL)
    s = lexical.bm25("What happens during egg retrieval in IVF?", docs)
    assert s.index(max(s)) == 1
    s2 = lexical.bm25("what is OHSS", ["Ovarian hyperstimulation syndrome\nfluid", "Embryo transfer\nthin tube"])
    assert s2[0] > 0 and s2[1] == 0


def _pilot_world(world):
    db = world["db"]
    clinic = world["a"]
    clinic.is_pilot = True
    db.commit()
    return db.query(CareProgram).filter_by(slug="a-weight-management").first()


def test_source_url_must_be_https(world):
    c, db = world["client"], world["db"]
    _as(world["staff"])
    pid = db.query(CareProgram).filter_by(slug="a-weight-management").first().id
    r = c.post(f"/api/care/studio/programs/{pid}/content",
               json={"kind": "document", "title": "x", "body": "y", "source_url": "http://evil"})
    assert r.status_code == 422
    r = c.post(f"/api/care/studio/programs/{pid}/content",
               json={"kind": "document", "title": "x", "body": "y", "source_url": "https://www.hfea.gov.uk/a/"})
    assert r.status_code == 200 and r.json()["source_url"] == "https://www.hfea.gov.uk/a/"


def test_pin_for_pilot_rejected_outside_pilot(world):
    c, db = world["client"], world["db"]
    _as(world["staff"])
    pid = db.query(CareProgram).filter_by(slug="a-weight-management").first().id
    it = c.post(f"/api/care/studio/programs/{pid}/content", json={"kind": "document", "title": "t", "body": "b"}).json()
    c.post(f"/api/care/studio/content/{it['id']}/submit", json={})
    assert c.post(f"/api/care/studio/content/{it['id']}/pin_for_pilot", json={}).status_code == 409


def test_pin_for_pilot_shows_in_review_label_and_specific_passage(world, stub_ai):
    c, db = world["client"], world["db"]
    _as(world["staff"])
    p = _pilot_world(world)
    ids = []
    for title, body in (("What IVF is", STEPS), ("Egg retrieval", RETRIEVAL)):
        it = c.post(f"/api/care/studio/programs/{p.id}/content",
                    json={"kind": "document", "title": title, "body": body,
                          "source_url": "https://www.hfea.gov.uk/treatments/"}).json()
        assert c.post(f"/api/care/studio/content/{it['id']}/submit", json={}).status_code == 200
        r = c.post(f"/api/care/studio/content/{it['id']}/pin_for_pilot", json={})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "in_review" and r.json()["status_label"] == "In clinical review"
        ids.append(it["id"])
    row = db.query(CareContentItem).filter_by(id=uuid.UUID(ids[1])).first()
    assert row.approved_by is None and row.approved_at is None  # not clinically approved
    hits = content.retrieve(db, program_id=p.id, clinic_id=world["a"].id, visible_course_ids=set(),
                            audience="patient", query="What happens during egg retrieval?")
    assert hits[0]["item_id"] == ids[1] and "needle" in hits[0]["content"]
    assert hits[0]["status_label"] == "In clinical review"
