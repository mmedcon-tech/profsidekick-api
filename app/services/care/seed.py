"""Synthetic demo data: two fictional clinics (A and B). Everything here is
DATA — the platform has no code path specific to these programs. All text is
fictional, labelled as demo, and not clinical guidance.

Run: python scripts/seed_care_demo.py  (idempotent)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session as DBSession

from app.database.models import (CareContentItem, CareCourse, CareLesson, CareProgram, Clinic, DoctorPersona,
                                 ProgramTemplate, RedFlagRule)
from app.services.care import content

REVIEWER = "Dr. Demo Reviewer (fictional)"
DEMO = "Fictional demo content — not medical advice."

CLINICS = {
    "demo-clinic-a": dict(
        name="Demo Clinic A (fictional)", branding={"primary_color": "#0f766e", "accent": "#ccfbf1"},
        description="A fictional multi-specialty clinic used to demonstrate the platform.",
        response_expectation="Demo Clinic A reads messages on weekdays, 9:00–17:00. Replies can take up to one working day. This service is not monitored at night or at weekends.",
        contact_routes=[
            {"key": "urgent", "label": "Clinic A urgent line (fictional)", "detail": "+00 000 0000 (demo number)", "hours": "weekdays 8:00–18:00"},
            {"key": "routine", "label": "Clinic A care team messages (fictional)", "detail": "via this app's “Ask my care team”", "hours": "weekdays 9:00–17:00"},
        ]),
    "demo-clinic-b": dict(
        name="Demo Clinic B (fictional)", branding={"primary_color": "#7c3aed", "accent": "#ede9fe"},
        description="A second fictional clinic, used to prove tenant isolation.",
        response_expectation="Demo Clinic B replies within two working days. Not monitored outside office hours.",
        contact_routes=[
            {"key": "urgent", "label": "Clinic B front desk (fictional)", "detail": "+00 111 1111 (demo number)", "hours": "weekdays 9:00–17:00"},
            {"key": "routine", "label": "Clinic B messages (fictional)", "detail": "via this app", "hours": "weekdays"},
        ]),
}

# program spec: (clinic, template slug, slug, name, description, persona, courses, content, flags)
PROGRAMS = [
    ("demo-clinic-a", "fertility", "a-fertility", "Fertility care",
     "Education between appointments for people going through fertility treatment at Demo Clinic A.",
     ("Dr. Lena Ardent (fictional)", "Fertility specialist", "female"),
     [("ivf-basics", "IVF basics", ["What happens in an IVF cycle", "Questions to bring to your consult"]),
      ("egg-retrieval", "Egg retrieval day", ["Preparing for retrieval", "After retrieval"])],
     [("faq", "What does an IVF cycle involve?", "An IVF cycle usually involves ovarian stimulation, monitoring visits, egg retrieval, fertilisation in the lab and embryo transfer. Your clinic will explain the exact steps and timing for your own plan.", None),
      ("patient_instruction", "Before egg retrieval (Clinic A demo instruction)", "Follow the fasting and arrival instructions in your personal plan from Demo Clinic A. Bring a companion who can take you home. If you have not received your personal plan, contact the care team.", "egg-retrieval")],
     [("Severe abdominal pain after retrieval", ["severe pain", "severe abdominal pain", "pain is getting worse"], "Call the Clinic A urgent line now. If you cannot reach it and pain is severe, call emergency services.", "urgent", "urgent", "egg-retrieval")]),
    ("demo-clinic-a", "plastic-surgery", "a-plastic-surgery", "Plastic surgery",
     "Preparation and recovery education for procedures at Demo Clinic A. Each procedure is its own course.",
     ("Dr. Marco Vell (fictional)", "Plastic surgeon", "male"),
     [("fat-transfer", "Fat transfer", ["How fat transfer works", "Recovery after fat transfer"]),
      ("dermal-fillers", "Dermal fillers", ["What dermal fillers are", "After your filler appointment"])],
     [("faq", "What is fat transfer?", "Fat transfer moves a small amount of your own fat, collected by liposuction, to another area. Your surgeon decides whether it is suitable for you at your consultation.", "fat-transfer"),
      ("faq", "How long do dermal fillers last?", "How long fillers last depends on the product and the treated area. Your clinician will tell you what to expect for your own treatment.", "dermal-fillers"),
      ("patient_instruction", "After dermal fillers (Clinic A demo instruction)", "Follow the aftercare sheet Demo Clinic A gave you at your appointment. Contact the clinic if anything on that sheet worries you.", "dermal-fillers")],
     [("Skin colour change or blanching near a filler site", ["skin turning white", "blanching", "skin turned white", "dusky", "skin colour change"], "Contact the Clinic A urgent line immediately — this needs to be assessed the same day.", "urgent", "urgent", "dermal-fillers"),
      ("Fever or spreading redness after surgery", ["fever", "spreading redness", "wound is hot"], "Contact the Clinic A urgent line today.", "same_day", "urgent", "fat-transfer")]),
    ("demo-clinic-a", "weight-management", "a-weight-management", "Weight management",
     "Weight-management education from Demo Clinic A, including how GLP-1 medicines work in general.",
     ("Dr. Priya Okon (fictional)", "Obesity medicine physician", "female"),
     [("glp1-education", "Understanding GLP-1 medicines", ["How GLP-1 medicines work", "Living with side effects"]),
      ("nutrition", "Nutrition foundations", ["Building balanced meals"])],
     [("faq", "How do GLP-1 medicines work?", "GLP-1 receptor agonists act like a gut hormone that helps regulate appetite and blood sugar. Your prescriber decides whether one is right for you, which product, and the dose schedule — this program does not.", "glp1-education"),
      ("faq", "Common side effects of GLP-1 medicines", "Nausea, reduced appetite and changes in bowel habits are commonly reported, especially early on. Tell your care team about side effects; do not change your medicine on your own.", "glp1-education")],
     [("Severe, persistent abdominal pain on a GLP-1 medicine", ["severe abdominal pain", "severe stomach pain", "pain going to my back"], "Stop and contact the Clinic A urgent line now, or emergency services if you cannot reach it.", "urgent", "urgent", "glp1-education")]),
    ("demo-clinic-b", "weight-management", "b-weight-management", "Weight programme",
     "Demo Clinic B's weight programme (fictional).",
     ("Dr. Sam Reiter (fictional)", "General practitioner", "male"),
     [("getting-started", "Getting started", ["Your first month"])],
     [("faq", "Clinic B secret onboarding note", "CLINIC-B-ONLY: this text must never appear for Clinic A patients.", None)],
     []),
]


def _get(db, model, **kw):
    return db.query(model).filter_by(**kw).first()


def seed_demo(db: DBSession) -> dict:
    now = datetime.utcnow()
    stats = {"clinics": 0, "programs": 0, "courses": 0, "content": 0, "red_flags": 0}
    clinics = {}
    for slug, spec in CLINICS.items():
        c = _get(db, Clinic, slug=slug)
        if not c:
            c = Clinic(id=uuid.uuid4(), slug=slug, status="active", is_demo=True, created_at=now, updated_at=now, **spec)
            db.add(c)
            stats["clinics"] += 1
        clinics[slug] = c
    db.flush()
    for i, (cslug, tslug, pslug, name, desc, persona, courses, items, flags) in enumerate(PROGRAMS):
        clinic = clinics[cslug]
        if _get(db, CareProgram, slug=pslug):
            continue
        tpl = _get(db, ProgramTemplate, slug=tslug)
        per = DoctorPersona(id=uuid.uuid4(), clinic_id=clinic.id, name=persona[0], title=persona[1], specialty=persona[1],
                            gender=persona[2], prompt="Warm, concise and plain-spoken.", is_demo=True, status="active",
                            created_at=now, updated_at=now)
        db.add(per)
        db.flush()
        p = CareProgram(id=uuid.uuid4(), slug=pslug, name=name, description=f"{desc} {DEMO}", clinic_ref_id=clinic.id,
                        clinic_id=clinic.slug, template_id=tpl.id if tpl else None, persona_id=per.id,
                        status="published", enrollment_policy="open", is_public=True, is_demo=True, position=i,
                        created_at=now, updated_at=now)
        db.add(p)
        db.flush()
        stats["programs"] += 1
        cmap = {}
        for j, (cs, title, lessons) in enumerate(courses):
            c = CareCourse(id=uuid.uuid4(), program_id=p.id, slug=cs, title=title, position=j, status="published",
                           created_at=now, updated_at=now)
            db.add(c)
            db.flush()
            cmap[cs] = c.id
            stats["courses"] += 1
            for k, lt in enumerate(lessons):
                db.add(CareLesson(id=uuid.uuid4(), course_id=c.id, title=lt, position=k, status="published",
                                  body=f"{lt}. {DEMO} Your clinic will give you the details that apply to you.",
                                  created_at=now, updated_at=now))
        for kind, title, body, cs in items:
            it = CareContentItem(id=uuid.uuid4(), lineage_id=uuid.uuid4(), version=1, clinic_id=clinic.id, program_id=p.id,
                                 course_id=cmap.get(cs), kind=kind, title=title, body=f"{body}\n\n{DEMO}",
                                 audience="patient", source=f"{clinic.name} demo library", status="approved",
                                 reviewer=REVIEWER, approved_at=now, expires_at=now + timedelta(days=365), is_demo=True,
                                 created_at=now, updated_at=now)
            db.add(it)
            db.flush()
            content.index_item(db, it)
            stats["content"] += 1
        for symptom, terms, action, urgency, route, cs in flags:
            db.add(RedFlagRule(id=uuid.uuid4(), clinic_id=clinic.id, program_id=p.id, course_id=cmap.get(cs),
                               symptom=symptom, match_terms=terms, clinic_action=f"{action} ({DEMO})", urgency=urgency,
                               contact_route=route, reviewer=REVIEWER, review_date=now, status="approved", is_demo=True,
                               created_at=now, updated_at=now))
            stats["red_flags"] += 1
    db.commit()
    return stats
