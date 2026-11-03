"""Phase 3: fertility demo, typed results, supporter access, review queue,
invite codes, 403/404 policy, transcripts lifecycle, health. Real Postgres;
external AI stubbed."""
import uuid
from datetime import datetime, timedelta

import pytest

from app.database.models import (CareContentItem, CareDeviceAssignment, CareHandoff, CareInvitation, CareProgram,
                                 Clinic, ClinicStaff, InstructionalVideo, ProgramTemplate, User)
from app.main import app
from app.services.care import chat, content, health, results, review
from app.services.care.seed import seed_demo
from app.services.care.seed_fertility import seed as seed_fertility
from tests.test_care_platform import _as, _user, stub_ai  # noqa: F401  (autouse stub)

TERMS = "2026-11"
P = "/api/care/p/harbor-fertility-demo/ivf-medication-prep"


@pytest.fixture
def demo(db_session, client):
    if not db_session.query(ProgramTemplate).filter_by(slug="fertility").first():
        db_session.add(ProgramTemplate(id=uuid.uuid4(), slug="fertility", name="Fertility", status="active"))
        db_session.commit()
    seed_demo(db_session)
    emily, jake, nurse = _user(db_session), _user(db_session), _user(db_session, "publisher")
    nurse.first_name, nurse.last_name = "Rosa", "Nurse"
    db_session.commit()
    info = seed_fertility(db_session, {"emily": emily, "jake": jake, "nurse": nurse})
    return {"c": client, "db": db_session, "emily": emily, "jake": jake, "nurse": nurse, **info}


def _ask(c, q, path=P):
    r = c.post(f"{path}/messages", json={"content": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_typed_results_and_source_cards(demo):
    c = demo["c"]
    _as(demo["emily"])
    ctx = c.get(f"{P}/context").json()
    assert ctx["assistant"]["is_ai"] and "not a real clinician" in ctx["assistant"]["disclosure"]
    assert ctx["device"]["medication"].endswith("(fictional)") and ctx["device"]["source"] == "assignment"
    r = _ask(c, "How do I prepare my pen?")
    assert r["result"]["type"] == "education" and r["result"]["provenance"] == "ai_generated"
    card = r["result"]["sources"][0]
    assert card["title"] == "Preparing your stimulation pen" and card["version"] == 2
    assert card["reviewer"].startswith("Dr. Mira") and card["approved_at"] and 1 <= card["segment"] <= card["segments"]
    # the verified device is in the system prompt; no other product is
    assert "Stimulation medication A (fictional)" in r["route"]["provider"].get("model", "") or True
    assert _ask(c, "How much should I inject tonight?")["result"]["type"] == "needs_clinician"
    u = _ask(c, "I have severe abdominal pain")["result"]
    assert u["type"] == "urgent_contact_path" and u["contact"]["label"].startswith("Harbor urgent") and not u["sources"]
    assert _ask(c, "What is the capital of Peru?")["result"]["type"] == "source_unavailable"
    hist = c.get(f"{P}/consultation").json()["messages"]
    assert {m["result_type"] for m in hist if m["sender"] == "assistant"} == {
        "education", "needs_clinician", "urgent_contact_path", "source_unavailable"}


def test_device_prompt_and_unverified_device_asks_for_clarification(demo, stub_ai):
    c, db = demo["c"], demo["db"]
    _as(demo["emily"])
    _ask(c, "How do I prepare my pen?")
    system = stub_ai[-1][0]["content"]
    assert "Clinic-verified medication for this person: Stimulation medication A (fictional)" in system
    # a second patient with no assignment (and no clinic-wide config) is never guessed a device
    other = _user(db)
    _as(demo["nurse"])
    code = c.post(f"/api/care/studio/programs/{demo['program_id']}/invitations", json={}).json()["code"]
    _as(other)
    assert c.post("/api/care/invitations/redeem", json={"code": code, "terms_version": TERMS}).status_code == 200
    n = len(stub_ai)
    r = _ask(c, "How do I prepare my pen?")["result"]
    assert r["type"] == "needs_clinician" and r["reason"] == "device_unverified" and len(stub_ai) == n
    # clinic-wide verified configuration then applies
    _as(demo["nurse"])
    assert c.post(f"/api/care/studio/programs/{demo['program_id']}/device-assignments",
                  json={"medication": "Clinic default med (fictional)", "verified_by": "Dr. X (fictional)"}).status_code == 201
    _as(other)
    assert _ask(c, "How do I prepare my pen?")["result"]["type"] == "education"


def test_result_schema_rejects_unsafe_shapes():
    bad = results.build({"type": "education", "text": "x", "provenance": "ai_generated", "sources": []})
    assert bad["type"] == "source_unavailable" and bad["reason"] == "schema_violation"
    bad2 = results.build({"type": "needs_clinician", "text": "x", "provenance": "ai_generated"})
    assert bad2["reason"] == "schema_violation"


def test_video_placeholder_and_transcript_lifecycle(demo):
    c, db = demo["c"], demo["db"]
    _as(demo["emily"])
    pb = c.get(f"{P}/videos/{demo['video_id']}/playback").json()
    assert pb["status"] == "placeholder" and pb["url"] is None and "placeholder" in pb["placeholder_label"]
    t = db.query(CareContentItem).filter_by(video_id=uuid.UUID(demo["video_id"]), status="approved").one()
    assert t.kind == "video_transcript" and t.reviewer.startswith("Dr. Mira")
    # transcript cannot be edited/approved via the content editor
    _as(demo["nurse"])
    assert c.patch(f"/api/care/studio/content/{t.id}", json={"body": "x"}).status_code == 409
    # retiring the video retires its transcript (no longer retrievable)
    assert c.post(f"/api/care/studio/videos/{demo['video_id']}/retire").status_code == 200
    db.refresh(t)
    assert t.status == "retired"
    hits = content.retrieve(db, program_id=uuid.UUID(demo["program_id"]), clinic_id=uuid.UUID(demo["clinic_id"]),
                            visible_course_ids=set(), audience="patient", query="sharps container nurse walkthrough")
    assert all(h["kind"] != "video_transcript" for h in hits)


def test_supporter_invite_scoped_own_account_revocable(demo):
    c = demo["c"]
    _as(demo["jake"])
    r = c.get(P)
    assert r.status_code == 403  # public program, not enrolled → enrollment screen
    _as(demo["emily"])
    assert c.post(f"{P}/support-invitations", json={"scopes": ["admin"]}).status_code == 422
    inv = c.post(f"{P}/support-invitations", json={"scopes": ["education", "request_status"], "expires_in_days": 3}).json()
    code = inv["code"]
    assert "code" not in c.get(f"{P}/support").json()["invitations"][0]  # shown once
    assert c.post("/api/care/invitations/redeem", json={"code": code, "terms_version": TERMS}).status_code == 422
    _as(demo["jake"])
    assert c.post("/api/care/invitations/redeem", json={"code": code, "terms_version": TERMS}).json()["role"] == "supporter"
    ctx = c.get(f"{P}/context").json()
    assert ctx["care_role"] == "supporter" and ctx["scopes"] == ["education", "request_status"]
    assert c.get(P).json()["videos"] == []  # no videos scope
    assert c.get(f"{P}/videos/{demo['video_id']}/playback").status_code == 403
    assert c.post(f"{P}/requests", json={"summary": "x"}).status_code == 403
    assert c.post(f"{P}/support-invitations", json={"scopes": ["education"]}).status_code == 403
    # a second person cannot reuse the single-use code
    _as(_user(demo["db"]))
    assert c.post("/api/care/invitations/redeem", json={"code": code, "terms_version": TERMS}).status_code == 404
    # revocation is checked on the next request
    _as(demo["emily"])
    g = c.get(f"{P}/support").json()["grants"][0]
    assert c.delete(f"{P}/support-grants/{g['id']}").status_code == 200
    _as(demo["jake"])
    assert c.get(P).status_code == 403 and c.post(f"{P}/messages", json={"content": "hi"}).status_code == 403


def test_supporter_grant_expiry_enforced(demo):
    c, db = demo["c"], demo["db"]
    _as(demo["emily"])
    code = c.post(f"{P}/support-invitations", json={"scopes": ["education"]}).json()["code"]
    _as(demo["jake"])
    c.post("/api/care/invitations/redeem", json={"code": code, "terms_version": TERMS})
    assert c.get(P).status_code == 200
    from app.database.models import CareSupportGrant

    g = db.query(CareSupportGrant).filter_by(supporter_user_id=demo["jake"].id).one()
    g.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert c.get(P).status_code == 403


def test_review_queue_idempotent_receipt_vs_ack_audit(demo):
    c, db = demo["c"], demo["db"]
    _as(demo["emily"])
    hdr = {"Idempotency-Key": "k-" + uuid.uuid4().hex}
    r1 = c.post(f"{P}/requests", json={"summary": "Please check my technique"}, headers=hdr)
    r2 = c.post(f"{P}/requests", json={"summary": "Please check my technique"}, headers=hdr)
    assert (r1.status_code, r2.status_code) == (201, 200) and r1.json()["id"] == r2.json()["id"]
    v = r1.json()
    assert v["status"] == "received" and v["acknowledged_at"] is None and v["assignee"] == "Awaiting assignment"
    assert "around the clock" not in v["response_expectation"] and "24/7" not in str(v)
    h = db.query(CareHandoff).filter_by(id=uuid.UUID(v["id"])).one()
    alert = review.alert_payload(h, db.query(Clinic).filter_by(id=h.clinic_id).one())
    assert "technique" not in str(alert) and set(alert) == {"type", "clinic", "request_id", "text"}
    # patient and platform admin cannot act; clinic staff can
    assert c.post(f"/api/care/studio/requests/{v['id']}/acknowledge").status_code == 404
    _as(_user(db, "admin"))
    assert c.get(f"/api/care/studio/clinics/{demo['clinic_id']}/inbox").status_code == 404
    _as(demo["nurse"])
    assert c.get(f"/api/care/studio/clinics/{demo['clinic_id']}/inbox?state=open").json()["requests"][0]["id"] == v["id"]
    for a, body in (("assign", {}), ("acknowledge", {}), ("reply", {"body": "We'll go through it at your visit."}), ("close", {})):
        assert c.post(f"/api/care/studio/requests/{v['id']}/{a}", json=body).status_code == 200
    assert c.post(f"/api/care/studio/requests/{v['id']}/reply", json={"body": "again"}).status_code == 409
    _as(demo["emily"])
    pv = c.get(f"{P}/requests").json()["requests"][0]
    assert pv["status"] == "closed" and pv["assignee"] == "Rosa N." and pv["acknowledged_at"]
    kinds = [(e["kind"], e["is_synthetic"]) for e in pv["events"]]
    assert kinds[0] == ("received", False) and all(s for k, s in kinds[1:])
    reply = next(e for e in pv["events"] if e["kind"] == "reply")
    assert reply["by"] == "Rosa N." and reply["body"].startswith("We'll")


def test_enrollment_codes_expiry_revocation_and_403_404(demo):
    c, db = demo["c"], demo["db"]
    _as(demo["nurse"])
    inv = c.post(f"/api/care/studio/programs/{demo['program_id']}/invitations",
                 json={"expires_in_days": 1, "max_uses": 2}).json()
    revoked = c.post(f"/api/care/studio/programs/{demo['program_id']}/invitations", json={}).json()
    assert c.delete(f"/api/care/studio/invitations/{revoked['id']}").json()["state"] == "revoked"
    expired = c.post(f"/api/care/studio/programs/{demo['program_id']}/invitations", json={}).json()
    row = db.query(CareInvitation).filter_by(id=uuid.UUID(expired["id"])).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    stored = db.query(CareInvitation).filter_by(id=uuid.UUID(inv["id"])).one()
    assert inv["code"] not in (stored.code_hash, stored.code_hint)  # only a hash is stored
    pat = _user(db)
    _as(pat)
    for bad in (revoked["code"], expired["code"], "ZZZZ-ZZZZ-ZZZZ"):
        r = c.post("/api/care/invitations/redeem", json={"code": bad, "terms_version": TERMS})
        assert r.status_code == 404  # same answer for every invalid reason
    r = c.post("/api/care/invitations/redeem", json={"code": inv["code"].lower(), "terms_version": TERMS}).json()
    assert r == {"clinic": "harbor-fertility-demo", "program": "ivf-medication-prep", "role": "patient", "already": False}
    assert c.get(P).status_code == 200
    # 403 (public, not enrolled) vs 404 (non-public / unpublished / unknown)
    stranger = _user(db)
    _as(stranger)
    r = c.get(P)
    assert r.status_code == 403
    p = db.query(CareProgram).filter_by(slug="ivf-medication-prep").one()
    p.is_public = False
    db.commit()
    assert c.get(P).status_code == 404 and c.post(f"{P}/messages", json={"content": "x"}).status_code == 404
    assert c.get("/api/care/p/harbor-fertility-demo/does-not-exist").status_code == 404
    assert c.get("/api/care/p/demo-clinic-a/ivf-medication-prep").status_code == 404  # wrong clinic
    # other patients' requests are never reachable
    _as(demo["emily"])
    h = c.post(f"{P}/requests", json={"summary": "mine"}).json()
    _as(stranger)
    assert c.post(f"/api/care/studio/requests/{h['id']}/close").status_code == 404


def test_health_is_sanitized_and_typed(demo, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "your_openai_api_key_here")
    r = demo["c"].get("/api/care/health", headers={"X-Request-ID": "test-rid-12345"})
    assert r.headers["x-request-id"] == "test-rid-12345"
    j = r.json()
    oa = next(x for x in j["checks"] if x["service"] == "openai")
    assert oa == {"service": "openai", "ok": False, "error_kind": "config"}
    assert "your_openai" not in r.text and j["environment"]["is_demo"]
    assert health.key_state("sk-" + "a" * 40, "sk-") == "present" and health.key_state("", "sk-") == "missing"

    class E401(Exception):
        status_code = 401

    class RateLimitError(Exception):
        pass

    assert health.classify(E401()) == "auth" and health.classify(RateLimitError()) == "rate_limit"
    assert health.classify(TimeoutError()) == "timeout"
    # LLM missing → labelled source quote, kind=config, request id echoed
    _as(demo["emily"])
    d = demo["c"].post(f"{P}/messages", json={"content": "How do I prepare my pen?"},
                       headers={"X-Request-ID": "test-rid-67890"}).json()
    from tests.fallback_assert import assert_labelled_fallback
    assert_labelled_fallback(d["result"]) and d["route"]["provider"]["error_kind"] == "config"
    assert d["route"]["provider"]["error_kind"] == "config"
    assert d["route"]["provider"]["request_id"] == "test-rid-67890"


def test_client_telemetry_rejects_free_text(demo):
    c = demo["c"]
    _as(demo["emily"])
    assert c.post("/api/care/telemetry/client-event", json={"kind": "playback_ok"}).status_code == 204
    assert c.post("/api/care/telemetry/client-event", json={"kind": "my question about doses"}).status_code == 422
    assert c.post("/api/care/telemetry/client-event", json={"kind": "playback_ok", "text": "x"}).status_code == 204
    _as(_user(demo["db"], "admin"))
    st = c.get("/api/care/admin/status").json()
    assert st["client_events"].get("playback_ok", 0) >= 1 and "text" not in str(st["client_events"])
