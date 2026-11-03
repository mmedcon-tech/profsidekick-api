"""MYOS sample content, loaded from seed/*.json. Idempotent, keyed by slug / seed_key.

* Never overwrites a row a publisher edited (content edited_at set, persona profile.edited_at set).
* All clinical content is seeded "in_review" with reviewer "Awaiting clinician" and hash-pinned;
  in_review content is only shown and retrieved in Pilot workspaces (see content.retrieve).
* ACL items are Draft placeholders with empty bodies until the hospital's material is provided.
Run: python -m scripts.seed_myos   (or `npm run seed` from the frontend repo).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from app.database.models import (CareContentItem, CareCourse, CareEntitlement, CareHandoff, CareHandoffEvent, CareLesson,
                                 CareProgram, CareProgramMembership, CareSupportGrant, Clinic, ClinicStaff, DoctorPersona,
                                 RedFlagRule, User, UserMemory)
from app.services.care import content, integrity

SEED_DIR = Path(os.getenv("SEED_DIR") or Path(__file__).resolve().parents[3] / "seed")
REVIEWER = "Awaiting clinician"
EXPIRY_DAYS = 90
MEMORY_TTL_DAYS = 365


def _load(name):
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def _env_true(k):
    return (os.getenv(k) or "").strip().lower() in ("1", "true", "yes")


def workspace_name(ws: dict) -> str:
    if ws.get("neutral_name") and not _env_true("BURJEEL_BRANDING_APPROVED"):
        return ws["neutral_name"]
    return ws["name"]


def _user(db, spec, now, password_hash):
    email = os.getenv(spec["env"]) if spec.get("env") else None
    email = (email or spec["email"]).strip().lower()
    u = db.query(User).filter((User.email == email) | (User.username == spec["username"])).first()
    if not u:
        u = User(id=uuid.uuid4(), username=spec["username"], email=email, password_hash=password_hash(),
                 first_name=spec["first"], last_name=spec["last"], role=spec["role"],
                 email_verified=True, is_approved=True, approved_at=now, created_at=now, updated_at=now)
        db.add(u)
        db.flush()
    return u


def _pin_in_review(item: CareContentItem, now):
    item.content_sha256 = item.approved_sha256 = integrity.content_hash(item)


def seed(db: DBSession, now: datetime | None = None) -> dict:
    from app.services.auth_service import AuthService
    now = now or datetime.utcnow()
    pw = os.getenv("SEED_PASSWORD") or "12345678"
    auth = AuthService()
    hashed = {}

    def password_hash():
        if "h" not in hashed:
            hashed["h"] = auth.hash_password(pw)
        return hashed["h"]

    sources = _load("sources.json")
    stats = {"created": 0, "kept_edited": 0}
    users = {s["key"]: _user(db, s, now, password_hash) for s in _load("accounts.json")}

    clinics = {}
    for ws in _load("workspaces.json"):
        c = db.query(Clinic).filter_by(slug=ws["slug"]).first()
        if not c:
            c = Clinic(id=uuid.uuid4(), slug=ws["slug"], created_at=now)
            db.add(c)
            stats["created"] += 1
        if not c.edited_at:  # staff renamed it: keep theirs
            c.name = workspace_name(ws)
        else:
            stats["kept_edited"] += 1
        c.is_pilot, c.languages, c.is_demo, c.status = ws["is_pilot"], ws["languages"], False, "active"
        c.branding, c.contact_routes, c.response_expectation = ws["branding"], ws["contact_routes"], ws["response_expectation"]
        if not c.edited_at:
            c.description = None
        c.updated_at = now
        db.flush()
        clinics[ws["slug"]] = c
    for s in _load("accounts.json"):
        for wslug in s.get("staff_of", []) + (list(clinics) if s["key"] in ("publisher", "myos_publisher") else []):
            if not db.query(ClinicStaff).filter_by(clinic_id=clinics[wslug].id, user_id=users[s["key"]].id).first():
                db.add(ClinicStaff(id=uuid.uuid4(), clinic_id=clinics[wslug].id, user_id=users[s["key"]].id, can_manage=True,
                                   can_publish=True, can_approve=True, can_view_clinical=True, created_at=now))
                db.flush()

    personas = {}
    for t in _load("twins.json"):
        p = db.query(DoctorPersona).filter_by(slug=t["slug"]).first()
        if p and (p.profile or {}).get("edited_at"):
            personas[t["slug"]] = p
            stats["kept_edited"] += 1
            continue
        if not p:
            p = DoctorPersona(id=uuid.uuid4(), slug=t["slug"], created_at=now)
            db.add(p)
        avatar = os.getenv(t["env_avatar"]) or t.get("fallback_avatar")
        voices = {"en": os.getenv(t["env_voice"]) or None}
        if t.get("env_voice_ar"):
            voices["ar"] = os.getenv(t["env_voice_ar"]) or None
        p.clinic_id = clinics[t["workspace"]].id
        p.name, p.title, p.specialty, p.gender = t["name"], t["title"], t["specialty"], t["gender"]
        p.liveavatar_avatar_id, p.voice_id = avatar, voices["en"]
        p.is_demo, p.status = False, "active"
        p.prompt = "Warm, calm, brief, plain language. Say 'conversation' and 'your care team'."
        p.first_messages = t["first_messages"]
        p.profile = {"photo": f"/avatars/{t['slug']}.jpg", "voices": voices, "reviewed_by": t["reviewed_by"],
                     "likeness_source": t["likeness_source"], "consent_file": t["consent_file"], "review_status": t["status"],
                     "modes": t["modes"], "programs": t["programs"], "workspace": t["workspace"],
                     "avatar_source": "env" if os.getenv(t["env_avatar"]) else ("fallback" if avatar else "none")}
        p.updated_at = now
        db.flush()
        personas[t["slug"]] = p

    programs = {}
    for spec in _load("programs.json"):
        clinic = clinics[spec["workspace"]]
        prog = db.query(CareProgram).filter_by(slug=spec["slug"]).first()
        if prog and prog.clinic_ref_id != clinic.id:
            # Merge: adopt the old program (e.g. legacy "IVF Care") into this workspace, keeping its patients.
            prog.clinic_ref_id, prog.clinic_id = clinic.id, clinic.slug
            for e in db.query(CareEntitlement).filter_by(program_id=prog.id).all():
                e.clinic_id = clinic.id
        if not prog:
            prog = CareProgram(id=uuid.uuid4(), slug=spec["slug"], clinic_ref_id=clinic.id, clinic_id=clinic.slug,
                               enrollment_policy="staff", is_public=True, created_at=now)
            db.add(prog)
            stats["created"] += 1
        prog.name, prog.description, prog.status, prog.position = spec["name"], spec["description"], spec["status"], spec["position"]
        prog.persona_id, prog.is_demo, prog.updated_at = personas[spec["twin"]].id, False, now
        prog.doctor_config = {**(prog.doctor_config or {}), "twin": spec["twin"],
                              "suggested_questions": spec.get("suggested_questions", [])}
        db.flush()
        programs[(spec["workspace"], spec["slug"].split(f"{spec['workspace']}-")[-1])] = prog
        courses = {}
        for pos, (cslug, ctitle) in enumerate(spec["stages"]):
            course = db.query(CareCourse).filter_by(program_id=prog.id, slug=cslug).first()
            if not course:
                course = CareCourse(id=uuid.uuid4(), program_id=prog.id, slug=cslug, created_at=now)
                db.add(course)
            course.title, course.position, course.status, course.updated_at = ctitle, pos, "published", now
            db.flush()
            courses[cslug] = course
        for it in spec["items"]:
            key = f"{spec['slug']}:{it['key']}"
            row = (db.query(CareContentItem).filter(CareContentItem.seed_key == key)
                   .order_by(CareContentItem.version.desc()).first())
            if row and row.edited_at:
                stats["kept_edited"] += 1
                continue
            src = sources.get(it["source"]) if it.get("source") else None
            body = it["body"] + (f"\n\nSuggested questions: " + " · ".join(it["suggested_questions"]) if it["suggested_questions"] else "")
            status = it.get("status", "in_review")
            if row and row.body == body and row.title == it["title"] and row.status == status:
                continue
            if row:
                content.invalidate_item(db, row.id)
                row.status = "retired"
                db.flush()
            new = CareContentItem(id=uuid.uuid4(), lineage_id=row.lineage_id if row else uuid.uuid4(),
                                  version=(row.version + 1) if row else 1, clinic_id=clinic.id, program_id=prog.id,
                                  course_id=courses[it["stage"]].id if it.get("stage") in courses else None,
                                  kind=it["kind"], title=it["title"], body=body, audience="both",
                                  source=src["title"] if src else None, source_url=src["url"] if src else None,
                                  source_type=it["source_type"], seed_key=key, status=status, reviewer=REVIEWER,
                                  expires_at=now + timedelta(days=EXPIRY_DAYS), is_demo=False, created_at=now, updated_at=now)
            db.add(new)
            db.flush()
            if status == "in_review" and new.body.strip():
                _pin_in_review(new, now)
                content.index_item(db, new)
            stats["created"] += 1
        for symptom, terms, action, urgency in spec.get("red_flags", []):
            if not db.query(RedFlagRule).filter_by(program_id=prog.id, symptom=symptom).first():
                db.add(RedFlagRule(id=uuid.uuid4(), clinic_id=clinic.id, program_id=prog.id, symptom=symptom, match_terms=terms,
                                   clinic_action=action, urgency=urgency, contact_route="emergency" if urgency == "emergency" else "urgent",
                                   reviewer=REVIEWER, review_date=now, status="approved", is_demo=False, created_at=now, updated_at=now))
    db.flush()

    ents = {}
    for s in _load("accounts.json"):
        for wslug, pslug, role, stage in s.get("programs", []):
            prog = programs[(wslug, pslug)]
            u = users[s["key"]]
            erole = "supporter" if role == "partner" else role
            e = db.query(CareEntitlement).filter_by(user_id=u.id, program_id=prog.id, revoked_at=None).first()
            if not e:
                e = CareEntitlement(id=uuid.uuid4(), user_id=u.id, clinic_id=clinics[wslug].id, program_id=prog.id,
                                    care_role=erole, source="staff_grant", terms_version="2026-11", created_at=now)
                db.add(e)
                db.flush()
            ents[(s["key"], pslug)] = e
            m = db.query(CareProgramMembership).filter_by(program_id=prog.id, user_id=u.id).first()
            if not m:
                db.add(CareProgramMembership(id=uuid.uuid4(), program_id=prog.id, user_id=u.id, care_role=role,
                                             treatment_stage=stage, joined_at=now, updated_at=now))
            if s.get("support_for"):
                patient = users[s["support_for"]]
                if not db.query(CareSupportGrant).filter_by(entitlement_id=e.id, revoked_at=None).first():
                    db.add(CareSupportGrant(id=uuid.uuid4(), clinic_id=clinics[wslug].id, program_id=prog.id,
                                            patient_user_id=patient.id, supporter_user_id=u.id, entitlement_id=e.id,
                                            scopes=["education", "videos"], created_at=now))
    db.flush()

    for r in _load("requests.json"):
        u, prog = users[r["user"]], programs[(r["workspace"], r["program"])]
        key = "seed:" + r["summary"][:60]
        if db.query(CareHandoff).filter_by(user_id=u.id, idempotency_key=key).first():
            continue
        at = now - timedelta(days=r["days_ago"], hours=1)
        h = CareHandoff(id=uuid.uuid4(), clinic_id=prog.clinic_ref_id, program_id=prog.id, user_id=u.id, reason=r["reason"],
                        summary=r["summary"], contact_route="urgent" if r.get("urgent") else "routine", status="received",
                        simulated=False, idempotency_key=key, received_at=at, created_at=at, updated_at=at)
        db.add(h)
        db.flush()
        db.add(CareHandoffEvent(id=uuid.uuid4(), handoff_id=h.id, kind="received", created_at=at))
        if r.get("reply"):
            staff = users[r["reply"]["by"]]
            h.status, h.assigned_to, h.acknowledged_at = "replied", staff.id, at + timedelta(hours=2)
            db.add(CareHandoffEvent(id=uuid.uuid4(), handoff_id=h.id, actor_user_id=staff.id, kind="reply",
                                    body=r["reply"]["body"], created_at=at + timedelta(hours=2)))

    # Earlier seed versions wrote these; drop them unless the person edited one (edited_at set).
    for old in LEGACY_MEMORY_TEXTS:
        for row in db.query(UserMemory).filter_by(content=old).all():
            if row.edited_at:
                stats["kept_edited"] += 1
            else:
                db.delete(row)
    # Studio memories used to sit on the real publisher login; they now belong to publisher@myos.test.
    if "publisher" in users and "myos_publisher" in users and users["publisher"].id != users["myos_publisher"].id:
        for row in db.query(UserMemory).filter_by(user_id=users["publisher"].id, topic="studio").all():
            if row.edited_at:
                stats["kept_edited"] += 1
            else:
                db.delete(row)
    for m in _load("memories.json"):
        u = users[m["user"]]
        topic = f"twin:{m['twin']}" if m["twin"] else "studio"
        if db.query(UserMemory).filter_by(user_id=u.id, topic=topic, content=m["text"]).first():
            continue
        # Relative dates count back from the seed date; a memory expires 12 months after its last use.
        at = now - timedelta(days=m["days_ago"])
        db.add(UserMemory(id=uuid.uuid4(), user_id=u.id, content=m["text"], importance=1.0, kind=m["category"], topic=topic,
                          evidence_quote=m["source"], status="active", visibility=["learner"], consent_basis="patient_consent",
                          times_seen=1, last_confirmed_at=at, expires_at=at + timedelta(days=MEMORY_TTL_DAYS),
                          created_at=at, updated_at=at))
    db.commit()
    return {"users": {k: v.email for k, v in users.items()}, "workspaces": list(clinics), **stats}


LEGACY_MEMORY_TEXTS = (
    "Sofia is 33 and in her first IVF cycle.", "Monitoring scan booked for Thursday morning.",
    "Prefers step by step instructions with short sentences.", "Asked how to travel with fridge medication next month.",
    "Ahmed plays football and wants to return to the game.", "Prefers Arabic for voice.", "Reviews new content on Monday mornings.",
)

LEGACY_CLINICS = ("demo-clinic-a", "demo-clinic-b", "harbor-fertility-demo")


def cleanup(db: DBSession) -> dict:
    """Run after seed(). Plastic surgery and Weight management move to the pilot workspace as Draft (hidden);
    "Fertility care" is merged into "IVF care" (dropped with its clinic); old demo clinics are deleted
    (CASCADE drops their rows); leftover smoke/UI test clinics are deactivated, not deleted."""
    out = {"deleted_clinics": [], "drafted": [], "deactivated": []}
    pilot = db.query(Clinic).filter_by(slug="myos-fertility-sf").first()
    for slug, name in (("a-plastic-surgery", "Plastic surgery"), ("a-weight-management", "Weight management")):
        p = db.query(CareProgram).filter_by(slug=slug).first()
        if p and pilot:
            p.status, p.name, p.is_demo = "draft", name, False
            p.clinic_ref_id, p.clinic_id, p.persona_id = pilot.id, pilot.slug, None
            db.query(CareEntitlement).filter_by(program_id=p.id).delete()
            for model in (CareContentItem, RedFlagRule):
                db.query(model).filter_by(program_id=p.id).update({"clinic_id": pilot.id})
            out["drafted"].append(slug)
    db.flush()
    for c in db.query(Clinic).filter(Clinic.slug.like("smoke-%") | Clinic.slug.like("ui-sleep-clinic-%")).all():
        c.status = "inactive"
        out["deactivated"].append(c.slug)
    for c in db.query(Clinic).filter(Clinic.slug.in_(LEGACY_CLINICS + ("demo-harbor",))).all():
        out["deleted_clinics"].append(c.slug)
        db.query(DoctorPersona).filter_by(clinic_id=c.id).delete()
        db.delete(c)
    db.commit()
    return out
