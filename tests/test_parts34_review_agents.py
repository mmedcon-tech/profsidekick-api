"""Part 3 (clinician review) and Part 4 (care memory, scoped agent access)."""
import uuid
from datetime import datetime, timedelta

from app.database.models import (CareAgentGrant, CareContentItem, CareProgram, CareProgramMembership, Clinic,
                                 ClinicStaff)
from app.services.care import agent_access, integrity
from tests.test_care_platform import _as, _user, stub_ai, world  # noqa: F401
from tests.test_myos_redesign import FERT, myos  # noqa: F401

API = "/api/care"


def _clinic(db):
    return db.query(Clinic).filter_by(slug="myos-fertility-sf").one()


def _staff(db, clinic, approve):
    u = _user(db)
    db.add(ClinicStaff(id=uuid.uuid4(), clinic_id=clinic.id, user_id=u.id, can_view_clinical=True,
                       can_approve=approve, display_name="Dr. Test Clinician" if approve else "Nurse Test"))
    db.commit()
    return u


def _patient(db, name):
    u = _user(db, name=name)
    prog = db.query(CareProgram).filter_by(slug="ivf-care").one()
    db.add(CareProgramMembership(id=uuid.uuid4(), program_id=prog.id, user_id=u.id, care_role="patient",
                                 authorized_scopes=[], joined_at=datetime.utcnow()))
    db.commit()
    return u


def _request(c, sofia):
    _as(sofia)
    r = c.post(f"{FERT}/ivf-care/requests", json={"reason": "patient_request", "summary": "Question about my scan"},
               headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ── Part 3 ──
def test_draft_states_are_separate_and_send_needs_exact_clinician_approval(myos):
    db, c = myos["db"], myos["client"]
    clinic = _clinic(db)
    nurse, doctor = _staff(db, clinic, False), _staff(db, clinic, True)
    rid = _request(c, myos["u"]["sofia"])
    _as(nurse)
    d = c.post(f"{API}/review/requests/{rid}/drafts", json={"body": "Your scan looks routine; we'll call you."})
    assert d.status_code == 201, d.text
    d = d.json()
    assert d["state"] == "awaiting_review" and d["state_label"] == "Awaiting review" and not d["clinician_approved"]
    assert c.post(f"{API}/review/drafts/{d['id']}/send").status_code == 409  # not reviewed
    assert c.post(f"{API}/review/drafts/{d['id']}/approve", json={"sha256": d["sha256"]}).status_code == 403  # nurse
    _as(doctor)
    assert c.post(f"{API}/review/drafts/{d['id']}/approve", json={"sha256": "0" * 64}).status_code == 409  # stale view
    r = c.post(f"{API}/review/drafts/{d['id']}/approve", json={"sha256": d["sha256"]}).json()
    assert r["state"] == "reviewed" and r["clinician_approved"] and r["approval"]["by"] == "Dr. Test Clinician"
    assert r["approval"]["sha256"] == d["sha256"] and r["approval"]["at"]
    _as(nurse)  # an edit after review invalidates it
    e = c.patch(f"{API}/review/drafts/{d['id']}", json={"body": "Changed text."}).json()
    assert e["state"] == "awaiting_review" and not e["clinician_approved"]
    assert c.post(f"{API}/review/drafts/{d['id']}/send").status_code == 409
    _as(doctor)
    c.post(f"{API}/review/drafts/{d['id']}/approve", json={"sha256": e["sha256"]})
    _as(nurse)
    s = c.post(f"{API}/review/drafts/{d['id']}/send").json()
    assert s["state"] == "sent" and s["state_label"] == "Sent" and s["clinician_approved"]
    assert c.post(f"{API}/review/drafts/{d['id']}/send").status_code == 409  # once only
    _as(myos["u"]["sofia"])
    mine = c.get(f"{FERT}/ivf-care/requests").json()["requests"]
    assert any(x["id"] == rid and x["status"] == "replied" for x in mine)


def test_material_clinician_approval_binds_exact_version(myos):
    db, c = myos["db"], myos["client"]
    clinic = _clinic(db)
    nurse, doctor = _staff(db, clinic, False), _staff(db, clinic, True)
    _as(nurse)
    q = c.get(f"{API}/review/clinics/{clinic.id}/review-queue").json()
    item = q["material"][0]
    assert item["status"] == "in_review" and not item["clinician_approved"]
    assert c.post(f"{API}/review/content/{item['id']}/clinician-approve", json={"sha256": item["sha256"]}).status_code == 403
    _as(doctor)
    x = c.post(f"{API}/review/content/{item['id']}/clinician-approve", json={"sha256": "f" * 64})
    assert x.status_code == 409, x.text
    r = c.post(f"{API}/review/content/{item['id']}/clinician-approve", json={"sha256": item["sha256"]}).json()
    assert r["status"] == "approved" and r["clinician_approved"] and r["approval"]["by"] == "Dr. Test Clinician"
    it = db.query(CareContentItem).filter_by(id=item["id"]).one()
    assert it.approved_sha256 == integrity.content_hash(it) == r["approval"]["sha256"]


def test_other_clinic_staff_cannot_see_queue(myos):
    db, c = myos["db"], myos["client"]
    other = db.query(Clinic).filter(Clinic.slug != "myos-fertility-sf").first()
    outsider = _staff(db, other, True)
    _as(outsider)
    assert c.get(f"{API}/review/clinics/{_clinic(db).id}/review-queue").status_code == 404


# ── Part 4 ──
def test_memory_is_preferences_only_and_patient_scoped(myos):
    db, c = myos["db"], myos["client"]
    _as(myos["u"]["sofia"])
    assert c.put(f"{API}/c/myos-fertility-sf/memory/preferred_name", json={"value": "Sofi"}).status_code == 200
    assert c.put(f"{API}/c/myos-fertility-sf/memory/preferred_name", json={"value": "225 IU Gonal-f"}).status_code == 422
    assert c.put(f"{API}/c/myos-fertility-sf/memory/dose", json={"value": "x"}).status_code == 422
    b = _patient(db, f"patb_{uuid.uuid4().hex[:6]}")
    _as(b)
    assert c.get(f"{API}/c/myos-fertility-sf/memory").json()["items"] == []
    _as(_user(db))  # not enrolled at this clinic
    assert c.get(f"{API}/c/myos-fertility-sf/memory").status_code == 404


def _grant(c, scopes=("preferences", "conversations"), ttl=7):
    r = c.post(f"{API}/c/myos-fertility-sf/agent-grants", json={"agent_label": "My assistant", "scopes": list(scopes),
                                                                "ttl_days": ttl})
    assert r.status_code == 201, r.text
    return r.json()


def _agent(c, token, tool):
    return c.get(f"{API}/agent/v1/{tool}", headers={"Authorization": f"Bearer {token}"} if token else {})


def test_agent_for_patient_a_cannot_read_patient_b_and_revocation_is_next_call(myos):
    db, c = myos["db"], myos["client"]
    a, b = _patient(db, f"pata_{uuid.uuid4().hex[:6]}"), _patient(db, f"patb_{uuid.uuid4().hex[:6]}")
    _as(b)
    c.put(f"{API}/c/myos-fertility-sf/memory/preferred_name", json={"value": "B-secret-name"})
    _as(a)
    c.put(f"{API}/c/myos-fertility-sf/memory/preferred_name", json={"value": "Alex"})
    g = _grant(c)
    assert "token" in g and g["token"].startswith("myos_agt_")
    assert db.query(CareAgentGrant).filter_by(id=g["id"]).one().token_sha256 != g["token"]
    r = _agent(c, g["token"], "preferences").json()
    assert r == {"preferences": {"preferred_name": "Alex"}}  # only A's data; no argument can select B
    convs = _agent(c, g["token"], "conversations").json()["conversations"]
    assert all("content" not in x for x in convs)
    assert _agent(c, None, "preferences").status_code == 401
    assert _agent(c, "myos_agt_forged", "preferences").status_code == 401
    c.delete(f"{API}/c/myos-fertility-sf/agent-grants/{g['id']}")
    assert _agent(c, g["token"], "preferences").status_code == 403  # very next call
    log = c.get(f"{API}/c/myos-fertility-sf/agent-grants").json()["log"]
    assert [(x["tool"], x["outcome"], x["reason"]) for x in log[:3]] == [
        ("get_my_preferences", "denied", "revoked"), ("list_my_conversations", "allowed", None),
        ("get_my_preferences", "allowed", None)]
    _as(b)  # B sees none of A's log and cannot revoke A's grant
    assert c.get(f"{API}/c/myos-fertility-sf/agent-grants").json()["log"] == []
    assert c.delete(f"{API}/c/myos-fertility-sf/agent-grants/{g['id']}").status_code == 404


def test_scope_expiry_and_enrolment_checked_per_call(myos):
    db, c = myos["db"], myos["client"]
    a = _patient(db, f"pata_{uuid.uuid4().hex[:6]}")
    _as(a)
    g = _grant(c, scopes=("preferences",))
    assert _agent(c, g["token"], "conversations").status_code == 403
    row = db.query(CareAgentGrant).filter_by(id=g["id"]).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert _agent(c, g["token"], "preferences").status_code == 403
    g2 = _grant(c, scopes=("preferences",))
    db.query(CareProgramMembership).filter_by(user_id=a.id).delete()
    db.commit()
    assert _agent(c, g2["token"], "preferences").status_code == 403
    reasons = [x.reason for x in db.query(agent_access.CareAgentAccessLog).filter_by(patient_user_id=a.id)]
    assert {"scope_not_granted", "expired", "not_enrolled"} <= set(reasons)
    assert c.post(f"{API}/c/myos-fertility-sf/agent-grants",
                  json={"agent_label": "x", "scopes": ["write_everything"], "ttl_days": 7}).status_code in (404, 422)


def test_deleting_a_request_removes_its_drafts_and_their_approvals(myos):
    from app.database.models import CareClinicianApproval, CareHandoff, CareReplyDraft
    db, c = myos["db"], myos["client"]
    doctor = _staff(db, _clinic(db), True)
    rid = _request(c, myos["u"]["sofia"])
    _as(doctor)
    d = c.post(f"{API}/review/requests/{rid}/drafts", json={"body": "Draft."}).json()
    c.post(f"{API}/review/drafts/{d['id']}/approve", json={"sha256": d["sha256"]})
    assert db.query(CareClinicianApproval).filter_by(subject_id=d["id"]).count() == 1
    db.query(CareHandoff).filter_by(id=rid).delete(synchronize_session=False)  # bulk SQL delete, no ORM cascade
    db.commit()
    db.expire_all()
    assert db.query(CareReplyDraft).filter_by(id=d["id"]).count() == 0
    assert db.query(CareClinicianApproval).filter_by(subject_id=d["id"]).count() == 0
