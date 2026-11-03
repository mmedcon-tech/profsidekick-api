"""Clinic-scoped peer community: isolation, pseudonymity, moderation, safety banner, exclusion from AI."""
import uuid
from datetime import datetime

from app.database.models import (CareCommunityPost, CareContentChunk, CarePatientMemory, CareProgram,
                                 CareProgramMembership, Clinic, ClinicStaff)
from app.services.care import content
from tests.test_care_platform import _as, _user, stub_ai, world  # noqa: F401
from tests.test_myos_redesign import myos  # noqa: F401

SF = "/api/care/c/myos-fertility-sf/community"


def _member(db, clinic_slug, name=None):
    u = _user(db, name=name)
    prog = db.query(CareProgram).join(Clinic, Clinic.id == CareProgram.clinic_ref_id).filter(Clinic.slug == clinic_slug).first()
    db.add(CareProgramMembership(id=uuid.uuid4(), program_id=prog.id, user_id=u.id, care_role="patient",
                                 authorized_scopes=[], joined_at=datetime.utcnow()))
    db.commit()
    return u


def _staff(db, clinic_slug, **perms):
    u = _user(db)
    clinic = db.query(Clinic).filter_by(slug=clinic_slug).one()
    db.add(ClinicStaff(id=uuid.uuid4(), clinic_id=clinic.id, user_id=u.id, display_name="Dr. Real Name", **perms))
    db.commit()
    return u


def _other_slug(db):
    return (db.query(Clinic).join(CareProgram, CareProgram.clinic_ref_id == Clinic.id)
            .filter(Clinic.slug != "myos-fertility-sf", Clinic.status == "active").first().slug)


def _post(c, body, space="starting-ivf", nick=None, base=SF):
    if nick:
        assert c.put(f"{base}/profile", json={"nickname": nick}).status_code == 200
    r = c.post(f"{base}/spaces/{space}/posts", json={"body": body})
    assert r.status_code == 201, r.text
    return r.json()


def test_two_clinics_are_isolated(myos):
    db, c = myos["db"], myos["client"]
    other = _other_slug(db)
    a, b = _member(db, "myos-fertility-sf"), _member(db, other)
    _as(a)
    pa = _post(c, "Hello from clinic A", nick="Willow")
    assert c.get(f"/api/care/c/{other}/community").status_code == 404
    _as(b)
    ob = f"/api/care/c/{other}/community"
    _post(c, "Hello from clinic B", nick="Willow", base=ob)  # same nickname is fine in another clinic
    assert c.get(SF).status_code == 404
    assert c.post(f"{SF}/posts/{pa['id']}/report", json={}).status_code == 404
    assert c.post(f"{ob}/posts/{pa['id']}/reactions", json={"kind": "hug"}).status_code == 404  # A's post via B
    bodies = [t["body"] for t in c.get(f"{ob}/spaces/starting-ivf").json()["threads"]]
    assert "Hello from clinic A" not in bodies and "Hello from clinic B" in bodies
    outsider = _user(db)
    _as(outsider)
    assert c.get(SF).status_code == 404


def test_pseudonymous_and_badges_are_server_side(myos):
    db, c = myos["db"], myos["client"]
    p = _member(db, "myos-fertility-sf", name="maria_rossi")
    _as(p)
    r = c.post(f"{SF}/spaces/starting-ivf/posts", json={"body": "hi"})
    assert r.status_code == 409 and r.json()["message"]["code"] == "nickname_required"
    assert c.put(f"{SF}/profile", json={"nickname": "maria_rossi"}).status_code == 422  # own username
    post = _post(c, "First week, nervous!", nick="Sunrise")
    assert post["author"] == "Sunrise" and post["badge"] is None
    raw = c.get(f"{SF}/spaces/starting-ivf").text
    assert "maria_rossi" not in raw and p.email not in raw and "Dr. Real Name" not in raw
    q = _member(db, "myos-fertility-sf")
    _as(q)
    assert c.put(f"{SF}/profile", json={"nickname": "sunrise"}).status_code == 409  # taken, case-insensitive
    doc = _staff(db, "myos-fertility-sf", can_approve=True)
    _as(doc)
    staff_post = _post(c, "Welcome, everyone.", nick="Clinic Team")
    assert staff_post["badge"] == "clinician"
    plain_staff = _staff(db, "myos-fertility-sf", can_publish=True)
    _as(plain_staff)
    assert _post(c, "Hi", nick="Publisher")["badge"] is None


def test_report_hide_restore_and_only_moderators(myos):
    db, c = myos["db"], myos["client"]
    a, b = _member(db, "myos-fertility-sf"), _member(db, "myos-fertility-sf")
    _as(a)
    post = _post(c, "Buy my supplements at example.com", nick="Spam")
    _as(b)
    assert c.post(f"{SF}/posts/{post['id']}/report", json={"reason": "Selling"}).status_code == 201
    assert c.get(f"{SF}/moderation").status_code == 403
    assert c.post(f"{SF}/posts/{post['id']}/moderate", json={"action": "hide"}).status_code == 403
    mod = _staff(db, "myos-fertility-sf", can_manage=True)
    _as(mod)
    q = c.get(f"{SF}/moderation").json()["items"]
    assert q[0]["id"] == post["id"] and q[0]["reports"] == 1 and q[0]["reasons"] == ["Selling"]
    assert c.post(f"{SF}/posts/{post['id']}/moderate", json={"action": "hide"}).json()["hidden"]
    _as(b)
    assert all(t["id"] != post["id"] for t in c.get(f"{SF}/spaces/starting-ivf").json()["threads"])
    _as(mod)
    q = c.get(f"{SF}/moderation").json()["items"]
    assert q[0]["hidden"] and q[0]["reports"] == 0  # report resolved, post still listed as hidden
    assert not c.post(f"{SF}/posts/{post['id']}/moderate", json={"action": "restore"}).json()["hidden"]
    _as(b)
    assert any(t["id"] == post["id"] for t in c.get(f"{SF}/spaces/starting-ivf").json()["threads"])
    other_mod = _staff(db, _other_slug(db), can_manage=True)
    _as(other_mod)
    assert c.get(f"{SF}/moderation").status_code == 404


def test_dose_questions_get_flag_and_replies_reactions_work(myos):
    db, c = myos["db"], myos["client"]
    a, b = _member(db, "myos-fertility-sf"), _member(db, "myos-fertility-sf")
    _as(a)
    med = _post(c, "I missed my dose tonight, should I take double tomorrow?", nick="Moon")
    calm = _post(c, "Anyone else find the waiting room playlist relaxing?")
    assert med["medical_flag"] and not calm["medical_flag"]
    _as(b)
    c.put(f"{SF}/profile", json={"nickname": "Star"})
    r = c.post(f"{SF}/spaces/starting-ivf/posts", json={"body": "Same here!", "parent_id": calm["id"]})
    assert r.status_code == 201
    assert c.post(f"{SF}/posts/{calm['id']}/reactions", json={"kind": "hug"}).json()["reactions"]["hug"] == 1
    assert c.post(f"{SF}/posts/{calm['id']}/reactions", json={"kind": "hug"}).json()["reactions"]["hug"] == 0  # toggle
    t = [t for t in c.get(f"{SF}/spaces/starting-ivf").json()["threads"] if t["id"] == calm["id"]][0]
    assert [x["author"] for x in t["replies"]] == ["Star"]


def test_community_posts_never_reach_retrieval_or_memory(myos):
    db, c = myos["db"], myos["client"]
    a = _member(db, "myos-fertility-sf")
    _as(a)
    marker = "zebracornflower acupuncture trick"
    _post(c, f"My {marker} worked wonders", nick="Fern")
    prog = db.query(CareProgram).filter_by(slug="ivf-care").one()
    hits = content.retrieve(db, program_id=prog.id, clinic_id=prog.clinic_ref_id, visible_course_ids=set(),
                            audience="patient", query=marker, top_k=10)
    assert all(marker not in (h.get("text") or h.get("body") or "") for h in hits)
    assert db.query(CareContentChunk).filter(CareContentChunk.content.ilike(f"%{marker}%")).count() == 0
    assert db.query(CarePatientMemory).filter_by(user_id=a.id).count() == 0
    assert db.query(CareCommunityPost).filter(CareCommunityPost.body.ilike(f"%{marker}%")).count() == 1


def test_ai_paths_do_not_read_community_tables():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app"
    readers = [p for p in root.rglob("*.py") if "CareCommunity" in p.read_text()]
    allowed = {"database/models.py", "services/care/community.py", "services/care/seed_myos.py"}
    assert {str(p.relative_to(root)) for p in readers} <= allowed


def test_community_routes_sit_behind_the_real_data_gate():
    from app.services.care.health import GATED_PREFIXES
    from app.api.care.community import router
    assert all(r.path.startswith(GATED_PREFIXES) for r in router.routes)
