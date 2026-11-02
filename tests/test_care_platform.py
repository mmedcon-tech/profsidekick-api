"""Care platform acceptance checks (spec §7) against a real Postgres.

External AI is stubbed; the live provider checks are separate (smoke script).
"""
import io
import uuid
from datetime import datetime, timedelta

import pytest

from app.database.models import (CareContentChunk, CareContentItem, CareProgram, Clinic, ClinicStaff,
                                 ProgramTemplate, User)
from app.dependencies.auth import get_current_user
from app.main import app
from app.services.care import chat, content
from app.services.care.seed import seed_demo

TERMS = "2026-11"


@pytest.fixture(autouse=True)
def stub_ai(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(content, "_try_embed", lambda texts: None)
    # shape-valid fake so the configured-key gate lets the stubbed model run
    monkeypatch.setattr(settings, "openai_api_key", "sk-" + "f" * 40)
    calls = []

    async def fake_complete(messages):
        calls.append(messages)
        return "From your clinic's material: see [1]."

    monkeypatch.setattr(chat, "_complete", fake_complete)
    return calls


def _user(db, role="subscriber", name=None):
    u = User(id=uuid.uuid4(), username=name or f"u_{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@example.com",
             password_hash="x", first_name="T", last_name="U", role=role)
    db.add(u)
    db.commit()
    return u


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


@pytest.fixture
def world(db_session, client):
    for slug, name in (("fertility", "Fertility"), ("plastic-surgery", "Plastic surgery"),
                       ("weight-management", "Weight management")):
        if not db_session.query(ProgramTemplate).filter_by(slug=slug).first():
            db_session.add(ProgramTemplate(id=uuid.uuid4(), slug=slug, name=name, status="active"))
    db_session.commit()
    seed_demo(db_session)
    a = db_session.query(Clinic).filter_by(slug="demo-clinic-a").first()
    b = db_session.query(Clinic).filter_by(slug="demo-clinic-b").first()
    staff = _user(db_session, "publisher")
    db_session.add(ClinicStaff(id=uuid.uuid4(), clinic_id=a.id, user_id=staff.id, can_manage=True, can_publish=True,
                               can_approve=True, can_view_clinical=True))
    db_session.commit()
    return {"a": a, "b": b, "staff": staff, "client": client, "db": db_session}


def _enroll(client, clinic, program):
    r = client.post(f"/api/care/p/{clinic}/{program}/enroll", json={"care_role": "patient", "terms_version": TERMS})
    assert r.status_code == 200, r.text


def test_switcher_lists_three_programs_with_branding(world):
    c, db = world["client"], world["db"]
    pat = _user(db)
    _as(pat)
    assert c.get("/api/care/me/programs").json()["programs"] == []
    for p in ("a-fertility", "a-plastic-surgery", "a-weight-management"):
        _enroll(c, "demo-clinic-a", p)
    progs = c.get("/api/care/me/programs").json()["programs"]
    assert [p["slug"] for p in progs] == ["a-fertility", "a-plastic-surgery", "a-weight-management"]
    assert all(p["clinic"]["slug"] == "demo-clinic-a" and p["branding"]["primary_color"] == "#0f766e" for p in progs)
    ps = c.get("/api/care/p/demo-clinic-a/a-plastic-surgery").json()
    assert [x["slug"] for x in ps["courses"]] == ["fat-transfer", "dermal-fillers"]  # separate pathways
    assert any(f["symptom"].startswith("Skin colour") for f in ps["red_flags"])
    assert any(i["kind"] == "patient_instruction" for i in ps["content"])
    # stale terms version is refused
    r = c.post("/api/care/p/demo-clinic-b/b-weight-management/enroll", json={"care_role": "patient", "terms_version": "2020"})
    assert r.status_code == 409


def test_fourth_program_new_persona_created_and_published_without_code(world):
    c, db = world["client"], world["db"]
    admin = _user(db, "admin")
    _as(admin)
    slug = f"sleep-{uuid.uuid4().hex[:5]}"
    t = c.post("/api/care/admin/templates", json={"slug": slug, "name": "Sleep medicine", "care_area": "Sleep"})
    assert t.status_code == 200, t.text
    # a publisher can't create templates
    pub = _user(db, "publisher")
    _as(pub)
    assert c.post("/api/care/admin/templates", json={"slug": slug + "x", "name": "X"}).status_code == 403
    # publisher creates a brand-new clinic, a persona, and the program
    cl = c.post("/api/care/studio/clinics", json={"slug": f"clinic-{slug}", "name": "Demo Sleep Clinic (fictional)",
                                                   "is_demo": True, "response_expectation": "Weekdays only.",
                                                   "contact_routes": [{"key": "urgent", "label": "Desk", "detail": "demo"}]})
    assert cl.status_code == 200, cl.text
    cid = cl.json()["id"]
    per = c.post(f"/api/care/studio/clinics/{cid}/personas", json={"name": "Dr. Noor Halden (fictional)", "title": "Sleep physician",
                 "voice_id": "voice-xyz", "variant": "white-coat", "liveavatar_avatar_id": "la-123", "gender": "female",
                 "prompt": "Calm and brief."})
    assert per.status_code == 200, per.text
    pr = c.post(f"/api/care/studio/clinics/{cid}/programs", json={"slug": f"p-{slug}", "name": "Sleep health",
                "template_id": t.json()["id"], "persona_id": per.json()["id"], "enrollment_policy": "open"})
    assert pr.status_code == 200, pr.text
    pid = pr.json()["id"]
    co = c.post(f"/api/care/studio/programs/{pid}/courses", json={"slug": "insomnia", "title": "Insomnia basics", "status": "published"})
    assert co.status_code == 200, co.text
    co = co.json()
    assert c.post(f"/api/care/studio/courses/{co['id']}/lessons", json={"title": "Sleep hygiene", "body": "b", "status": "published"}).status_code == 200
    it = c.post(f"/api/care/studio/programs/{pid}/content", json={"kind": "faq", "language": "en", "audience": "patient", "title": "What is CBT-I?",
                "body": "CBT-I is a structured insomnia therapy that your clinic may offer.", "course_id": co["id"]}).json()
    assert it["status"] == "draft"
    assert c.post(f"/api/care/studio/content/{it['id']}/submit", json={}).status_code == 200
    # creator has publish but NOT clinical approval
    assert c.post(f"/api/care/studio/content/{it['id']}/approve", json={"reviewer": "Dr. R"}).status_code == 403
    # patients can't see the draft program
    pat = _user(db)
    _as(pat)
    assert c.get(f"/api/care/preview/clinic-{slug}/p-{slug}").status_code == 404
    # grant an approver, approve, publish
    appr = _user(db, "publisher")
    _as(pub)
    assert c.post(f"/api/care/studio/clinics/{cid}/staff", json={"user": appr.username, "can_approve": True}).status_code == 200
    _as(appr)
    assert c.post(f"/api/care/studio/content/{it['id']}/approve", json={}).status_code == 422  # reviewer name required
    assert c.post(f"/api/care/studio/content/{it['id']}/approve", json={"reviewer": "Dr. R (fictional)"}).json()["status"] == "approved"
    assert c.post(f"/api/care/studio/programs/{pid}/publish").status_code == 403  # approver lacks publish
    _as(pub)
    assert c.post(f"/api/care/studio/programs/{pid}/publish").json()["status"] == "published"
    _as(pat)
    assert any(p["slug"] == f"p-{slug}" for p in c.get("/api/care/catalog").json()["programs"])
    _enroll(c, f"clinic-{slug}", f"p-{slug}")
    view = c.get(f"/api/care/p/clinic-{slug}/p-{slug}").json()
    assert view["program"]["persona"]["name"] == "Dr. Noor Halden (fictional)"
    assert view["program"]["template"]["name"] == "Sleep medicine"
    r = c.post(f"/api/care/p/clinic-{slug}/p-{slug}/messages", json={"content": "What is CBT-I therapy?"}).json()
    assert r["reply"]["sources"][0]["title"] == "What is CBT-I?"
    assert r["context"] == {"clinic": f"clinic-{slug}", "program": f"p-{slug}", "consultation_id": r["context"]["consultation_id"]}


def test_draft_expired_superseded_not_retrievable(world, stub_ai):
    c, db, staff = world["client"], world["db"], world["staff"]
    _as(staff)
    pid = str(db.query(CareProgram).filter_by(slug="a-weight-management").first().id)
    it = c.post(f"/api/care/studio/programs/{pid}/content", json={"kind": "faq", "title": "Zebrafruit snack guide",
                "body": "Version one says zebrafruit snacks are fine."}).json()
    pat = _user(db)
    _as(pat)
    _enroll(c, "demo-clinic-a", "a-weight-management")
    ask = lambda: c.post("/api/care/p/demo-clinic-a/a-weight-management/messages", json={"content": "zebrafruit snacks?"}).json()  # noqa: E731
    assert ask()["reply"]["sources"] == []  # draft: not retrievable
    _as(staff)
    c.post(f"/api/care/studio/content/{it['id']}/submit", json={})
    c.post(f"/api/care/studio/content/{it['id']}/approve", json={"reviewer": "Dr. R"})
    _as(pat)
    r = ask()
    assert r["reply"]["sources"][0]["version"] == 1
    # edit approved → new draft v2; v1 still active until v2 approved
    _as(staff)
    v2 = c.patch(f"/api/care/studio/content/{it['id']}", json={"body": "Version two replaces zebrafruit advice."}).json()
    assert v2["version"] == 2 and v2["status"] == "draft"
    c.post(f"/api/care/studio/content/{v2['id']}/submit", json={})
    c.post(f"/api/care/studio/content/{v2['id']}/approve", json={"reviewer": "Dr. R"})
    db.expire_all()
    assert db.query(CareContentItem).filter_by(id=uuid.UUID(it["id"])).first().status == "retired"
    assert db.query(CareContentChunk).filter_by(item_id=uuid.UUID(it["id"])).count() == 0
    _as(pat)
    r = ask()
    assert [s["version"] for s in r["reply"]["sources"]] == [2]
    assert "Version two" in stub_ai[-1][0]["content"] and "Version one" not in stub_ai[-1][0]["content"]
    # expired → gone
    item = db.query(CareContentItem).filter_by(id=uuid.UUID(v2["id"])).first()
    item.expires_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    assert ask()["reply"]["sources"] == []


def test_cross_clinic_and_course_isolation(world, stub_ai):
    c, db, staff = world["client"], world["db"], world["staff"]
    pat = _user(db)
    _as(pat)
    _enroll(c, "demo-clinic-a", "a-weight-management")
    # not enrolled in Clinic B → denied, even by direct API
    assert c.get("/api/care/p/demo-clinic-b/b-weight-management").status_code == 403
    assert c.post("/api/care/p/demo-clinic-b/b-weight-management/messages", json={"content": "onboarding note"}).status_code == 403
    # Clinic A program addressed under Clinic B's slug → 404
    assert c.get("/api/care/p/demo-clinic-b/a-weight-management").status_code == 404
    r = c.post("/api/care/p/demo-clinic-a/a-weight-management/messages", json={"content": "Clinic B secret onboarding note"}).json()
    assert "CLINIC-B-ONLY" not in str(r) and "CLINIC-B-ONLY" not in str(stub_ai)
    # staff of A cannot touch B through the studio
    _as(staff)
    b = world["b"]
    assert c.get(f"/api/care/studio/clinics/{b.id}/programs").status_code == 404
    bprog = db.query(CareProgram).filter_by(slug="b-weight-management").first()
    assert c.post(f"/api/care/studio/programs/{bprog.id}/content", json={"kind": "faq", "title": "x", "body": "y"}).status_code == 404
    # course-gated content: invisible without a course entitlement
    aprog = db.query(CareProgram).filter_by(slug="a-weight-management").first()
    co = c.post(f"/api/care/studio/programs/{aprog.id}/courses", json={"slug": f"vip-{uuid.uuid4().hex[:4]}", "title": "Gated",
                "status": "published", "requires_entitlement": True}).json()
    it = c.post(f"/api/care/studio/programs/{aprog.id}/content", json={"kind": "faq", "title": "Quokka protocol",
                "body": "Quokka gated course material.", "course_id": co["id"]}).json()
    c.post(f"/api/care/studio/content/{it['id']}/submit", json={})
    c.post(f"/api/care/studio/content/{it['id']}/approve", json={"reviewer": "Dr. R"})
    up = c.post(f"/api/care/studio/programs/{aprog.id}/videos", data={"title": "Gated video", "course_id": co["id"]},
                files={"file": ("v.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")}).json()
    assert up["status"] == "draft"
    _as(pat)
    vid = f"/api/care/p/demo-clinic-a/a-weight-management/videos/{up['id']}/playback"
    assert c.get(vid).status_code == 404  # draft video
    _as(staff)
    c.post(f"/api/care/studio/videos/{up['id']}/submit", json={})
    c.post(f"/api/care/studio/videos/{up['id']}/approve", json={"reviewer": "Dr. R"})
    _as(pat)
    assert c.get(vid).status_code == 404  # approved but in a gated course
    assert all(x["title"] != "Gated" for x in c.get("/api/care/p/demo-clinic-a/a-weight-management").json()["courses"])
    r = c.post("/api/care/p/demo-clinic-a/a-weight-management/messages", json={"content": "quokka protocol"}).json()
    assert r["reply"]["sources"] == []
    _as(staff)
    assert c.post(f"/api/care/studio/programs/{aprog.id}/entitlements", json={"user": pat.username, "course_id": co["id"]}).status_code == 200
    _as(pat)
    assert c.post("/api/care/p/demo-clinic-a/a-weight-management/messages", json={"content": "quokka protocol"}).json()["reply"]["sources"][0]["title"] == "Quokka protocol"
    pb = c.get(vid).json()
    assert "/api/care/videos/" in pb["url"]
    path = pb["url"].split("testserver")[-1]
    assert c.get(path).status_code == 200
    assert c.get(path.replace("sig=", "sig=0")).status_code == 403  # tampered signature
    # legacy endpoint does not expose care videos
    assert c.get(f"/api/fertility/videos/{up['id']}").status_code == 404


def test_red_flag_and_personal_judgment_routes(world, stub_ai):
    c, db = world["client"], world["db"]
    pat = _user(db)
    _as(pat)
    _enroll(c, "demo-clinic-a", "a-plastic-surgery")
    _enroll(c, "demo-clinic-a", "a-weight-management")
    n = len(stub_ai)
    r = c.post("/api/care/p/demo-clinic-a/a-plastic-surgery/messages", json={"content": "the skin near my filler is blanching"}).json()
    assert r["route"]["kind"] == "red_flag" and r["route"]["urgency"] == "urgent"
    assert "Clinic A urgent line" in r["reply"]["content"] and "not monitored" in r["reply"]["content"]
    r = c.post("/api/care/p/demo-clinic-a/a-weight-management/messages", json={"content": "Should I increase my dose of semaglutide next week?"}).json()
    assert r["route"]["kind"] == "personal_judgment" and r["route"]["handoff_offered"]
    r2 = c.post("/api/care/p/demo-clinic-a/a-plastic-surgery/messages", json={"content": "Am I a good candidate for fat transfer?"}).json()
    assert r2["route"]["kind"] == "personal_judgment"
    assert len(stub_ai) == n  # the model was never asked
    # routine question → approved source
    r = c.post("/api/care/p/demo-clinic-a/a-weight-management/messages", json={"content": "How do GLP-1 medicines work?"}).json()
    assert r["route"]["kind"] == "education" and r["reply"]["sources"][0]["title"] == "How do GLP-1 medicines work?"
    h = c.post("/api/care/p/demo-clinic-a/a-weight-management/handoffs", json={"reason": "personal_judgment", "summary": "dose question"}).json()
    assert h["simulated"] and "Simulated" in h["note"]
    # platform admin does not see clinical handoffs; clinic staff with the flag does
    admin = _user(db, "admin")
    _as(admin)
    assert c.get(f"/api/care/studio/clinics/{world['a'].id}/handoffs").status_code == 404
    _as(world["staff"])
    assert any(x["summary"] == "dose question" for x in c.get(f"/api/care/studio/clinics/{world['a'].id}/handoffs").json()["handoffs"])


def test_llm_failure_is_labeled_not_disguised(world, monkeypatch):
    c, db = world["client"], world["db"]

    async def boom(messages):
        raise RuntimeError("401")

    monkeypatch.setattr(chat, "_complete", boom)
    pat = _user(db)
    _as(pat)
    _enroll(c, "demo-clinic-a", "a-weight-management")
    r = c.post("/api/care/p/demo-clinic-a/a-weight-management/messages", json={"content": "How do GLP-1 medicines work?"}).json()
    assert r["route"]["provider"]["llm"] == "error"
    assert r["reply"]["provenance"] == "source_quote" and r["reply"]["content"].startswith(chat.FALLBACK_INTRO)


def test_public_preview_and_unpublish(world):
    c, db, staff = world["client"], world["db"], world["staff"]
    _as(_user(db))
    pv = c.get("/api/care/preview/demo-clinic-a/a-fertility").json()
    assert "content" not in pv and "red_flags" not in pv and "lessons" not in str(pv["courses"])
    assert c.get("/api/care/p/demo-clinic-a/a-fertility").status_code == 403  # preview never unlocks
    _as(staff)
    p = db.query(CareProgram).filter_by(slug="a-fertility").first()
    c.post(f"/api/care/studio/programs/{p.id}/unpublish")
    _as(_user(db))
    assert c.get("/api/care/preview/demo-clinic-a/a-fertility").status_code == 404
    _as(staff)
    c.post(f"/api/care/studio/programs/{p.id}/publish")


def test_admin_integrations_never_return_secrets(world, monkeypatch):
    from app.config import settings

    c, db = world["client"], world["db"]
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-SECRETSECRETSECRET")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "your_elevenlabs_key_here")
    _as(_user(db))
    assert c.get("/api/care/admin/integrations").status_code == 403
    _as(_user(db, "admin"))
    r = c.get("/api/care/admin/integrations")
    body = r.text
    assert r.status_code == 200 and "SECRET" not in body and "your_elevenlabs" not in body
    j = r.json()
    assert j["openai"]["state"] == "present" and j["elevenlabs"]["state"] == "placeholder"


def _tiny_pdf(lines):
    """A minimal one-page text PDF built by hand (no extra dependency)."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    stream = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_upload_pdf_creates_draft_then_retrievable_after_approval(world, stub_ai):
    c, db, staff = world["client"], world["db"], world["staff"]
    _as(staff)
    pid = str(db.query(CareProgram).filter_by(slug="a-weight-management").first().id)
    pdf = _tiny_pdf(["Wombatberry weigh-in policy", "Wombatberry weigh-ins run 7:30 to 9:30 am, Monday to Saturday."])
    r = c.post(f"/api/care/studio/programs/{pid}/content/upload", data={"title": "Wombatberry weigh-ins"},
               files={"file": ("weighins.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    it = r.json()
    assert it["status"] == "draft" and "7:30 to 9:30" in it["body"] and it["source"] == "weighins.pdf"
    assert c.post(f"/api/care/studio/programs/{pid}/content/upload",
                  files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 422
    assert c.post(f"/api/care/studio/programs/{pid}/content/upload",
                  files={"file": ("empty.txt", b"   ", "text/plain")}).status_code == 422
    pat = _user(db)
    _as(pat)
    _enroll(c, "demo-clinic-a", "a-weight-management")
    assert c.post(f"/api/care/studio/programs/{pid}/content/upload",
                  files={"file": ("a.txt", b"hi", "text/plain")}).status_code in (403, 404)
    ask = lambda: c.post("/api/care/p/demo-clinic-a/a-weight-management/messages", json={"content": "wombatberry weigh-ins hours?"}).json()  # noqa: E731
    assert all(s["item_id"] != it["id"] for s in ask()["reply"]["sources"])  # draft: never retrieved
    _as(staff)
    c.post(f"/api/care/studio/content/{it['id']}/submit", json={})
    c.post(f"/api/care/studio/content/{it['id']}/approve", json={"reviewer": "Dr. R"})
    _as(pat)
    top = ask()["reply"]["sources"][0]
    assert top["title"] == "Wombatberry weigh-ins" and top["version"] == 1 and top["status_label"].startswith("Approved")
