"""Fictional fertility demo: Harbor Fertility (demo), patient Emily (34) and her
partner Jake. Synthetic data only. No real clinic, clinician, product or
patient. No injection footage exists or is generated: the video record is an
approved transcript with an explicit footage placeholder.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session as DBSession

from app.database.models import (CareContentItem, CareCourse, CareDeviceAssignment, CareEntitlement, CareLesson,
                                 CareProgram, Clinic, ClinicStaff, DoctorPersona, InstructionalVideo, ProgramTemplate,
                                 RedFlagRule, User)
from app.services.care import content

CLINIC = "harbor-fertility-demo"
PROGRAM = "ivf-medication-prep"
REVIEWER = "Dr. Mira Solberg (fictional reviewer)"
DEMO = "Fictional demo content for a product demonstration — not medical advice."
MED = "Stimulation medication A (fictional)"
DEVICE = "Demo multi-dose pen (fictional)"

GUIDE = """Preparing your stimulation pen — Harbor demo guide

Before you start, check that the medication and pen match the medication sheet Harbor Fertility gave you. If the name on the box is different, stop and contact the care team before using it.

Wash your hands and lay out what you need on a clean surface: the pen, a new pen needle, an alcohol swab and your sharps container.

Check the expiry date and look at the liquid through the pen window. Do not use it if it looks cloudy or contains particles, unless your clinic's sheet says that is expected.

Attach a new needle for every injection and remove both caps. Your clinic's sheet and nurse teach you the dose to dial and the timing — this guide does not cover doses or timing.

After use, put the needle straight into the sharps container and store the pen as the box and your clinic's sheet describe.""" 

TRANSCRIPT = """In this short guide a Harbor Fertility nurse walks through preparing a multi-dose pen. First, compare the pen and box with your medication sheet. Wash your hands and lay everything out on a clean surface. Check the expiry date and the liquid in the pen window. Attach a new needle and remove both caps. The dose you dial and when you inject come from your own plan and your nurse, not from this video. Finally, dispose of the needle in your sharps container."""


def _get(db, model, **kw):
    return db.query(model).filter_by(**kw).first()


def seed(db: DBSession, users: dict | None = None) -> dict:
    """users: {"emily": User, "jake": User, "nurse": User} (optional)."""
    now = datetime.utcnow()
    clinic = _get(db, Clinic, slug=CLINIC)
    if not clinic:
        clinic = Clinic(id=uuid.uuid4(), slug=CLINIC, name="Harbor Fertility (fictional demo clinic)", status="active",
                        is_demo=True, created_at=now, updated_at=now,
                        description="A fictional fertility clinic used to demonstrate MYOS. Not a real clinic.",
                        branding={"primary_color": "#0e7490", "accent": "#cffafe"},
                        response_expectation=("Harbor's care team reads messages on weekdays, 8:00–17:00 and replies "
                                              "within one working day. Messages are not monitored at night or at weekends."),
                        contact_routes=[
                            {"key": "urgent", "label": "Harbor urgent nurse line (fictional)",
                             "detail": "+00 222 2222 (demo number)", "hours": "weekdays 8:00–18:00"},
                            {"key": "routine", "label": "Harbor care team messages (fictional)",
                             "detail": "via “Ask my care team” in this app", "hours": "weekdays 8:00–17:00"}])
        db.add(clinic)
        db.flush()
    p = _get(db, CareProgram, slug=PROGRAM)
    if not p:
        per = DoctorPersona(id=uuid.uuid4(), clinic_id=clinic.id, name="Ann (AI assistant)",
                            title="AI care assistant — demo avatar identity, not a clinician",
                            specialty="Fertility medication education", gender="female",
                            prompt="Warm, calm and brief. Always plain language.", is_demo=True, status="active",
                            created_at=now, updated_at=now)
        db.add(per)
        db.flush()
        tpl = _get(db, ProgramTemplate, slug="fertility")
        p = CareProgram(id=uuid.uuid4(), slug=PROGRAM, name="IVF medication preparation",
                        description=f"Help preparing for stimulation medication between nurse visits. {DEMO}",
                        clinic_ref_id=clinic.id, clinic_id=clinic.slug, template_id=tpl.id if tpl else None,
                        persona_id=per.id, status="published", enrollment_policy="staff", is_public=True,
                        is_demo=True, position=0, created_at=now, updated_at=now)
        db.add(p)
        db.flush()
        course = CareCourse(id=uuid.uuid4(), program_id=p.id, slug="medication-prep", title="Medication preparation",
                            position=0, status="published", created_at=now, updated_at=now)
        db.add(course)
        db.flush()
        for k, lt in enumerate(["Your medication sheet", "Preparing the pen", "Sharps and storage"]):
            db.add(CareLesson(id=uuid.uuid4(), course_id=course.id, title=lt, position=k, status="published",
                              body=f"{lt}. {DEMO} Your clinic's sheet and nurse give the details for you.",
                              created_at=now, updated_at=now))
        lineage = uuid.uuid4()
        old = CareContentItem(id=uuid.uuid4(), lineage_id=lineage, version=1, clinic_id=clinic.id, program_id=p.id,
                              course_id=course.id, kind="patient_instruction", title="Preparing your stimulation pen",
                              body=GUIDE.split("\n\n", 2)[1], audience="both", source="Harbor demo library",
                              status="retired", reviewer=REVIEWER, approved_at=now - timedelta(days=90), is_demo=True,
                              created_at=now - timedelta(days=95), updated_at=now - timedelta(days=30))
        guide = CareContentItem(id=uuid.uuid4(), lineage_id=lineage, version=2, clinic_id=clinic.id, program_id=p.id,
                                course_id=course.id, kind="patient_instruction", title="Preparing your stimulation pen",
                                body=f"{GUIDE}\n\n{DEMO}", audience="both", source="Harbor demo library",
                                status="approved", reviewer=REVIEWER, approved_at=now - timedelta(days=30),
                                expires_at=now + timedelta(days=335), is_demo=True,
                                created_at=now - timedelta(days=31), updated_at=now - timedelta(days=30))
        faq = CareContentItem(id=uuid.uuid4(), lineage_id=uuid.uuid4(), version=1, clinic_id=clinic.id, program_id=p.id,
                              course_id=None, kind="faq", title="What is ovarian stimulation?",
                              body=("Ovarian stimulation uses medication to help several eggs mature in one cycle. "
                                    "Harbor's team monitors you with scans and blood tests and tells you about any "
                                    f"change to your plan.\n\n{DEMO}"), audience="both", source="Harbor demo library",
                              status="approved", reviewer=REVIEWER, approved_at=now - timedelta(days=30),
                              expires_at=now + timedelta(days=335), is_demo=True, created_at=now, updated_at=now)
        db.add_all([old, guide, faq])
        db.flush()
        content.index_item(db, guide)
        content.index_item(db, faq)
        video = InstructionalVideo(id=uuid.uuid4(), title="Preparing a multi-dose pen (nurse walkthrough)",
                                   description="Approved transcript. Approved footage has not been provided yet.",
                                   audience="both", language="en", clinic_id=clinic.slug, approval_status="approved",
                                   status="approved", version="1", transcript=TRANSCRIPT, reviewer=REVIEWER,
                                   approved_at=now - timedelta(days=30), program_id=p.id, course_id=course.id,
                                   position=0, medication_name=MED, device_name=DEVICE, created_at=now)
        db.add(video)
        db.flush()
        content.sync_video_transcript(db, video, None)
        for symptom, terms, action, urgency in [
            ("Severe abdominal pain or bloating", ["severe abdominal pain", "severe bloating", "very swollen", "severe pain"],
             "Call the Harbor urgent nurse line now. If you cannot reach it and symptoms are severe, call emergency services.", "urgent"),
            ("Shortness of breath", ["short of breath", "shortness of breath", "can't breathe", "cannot breathe"],
             "Call emergency services now.", "emergency")]:
            db.add(RedFlagRule(id=uuid.uuid4(), clinic_id=clinic.id, program_id=p.id, symptom=symptom, match_terms=terms,
                               clinic_action=f"{action} ({DEMO})", urgency=urgency, contact_route="urgent",
                               reviewer=REVIEWER, review_date=now, status="approved", is_demo=True,
                               created_at=now, updated_at=now))
        db.flush()
    guide = (db.query(CareContentItem).filter_by(program_id=p.id, kind="patient_instruction", status="approved").first())
    video = db.query(InstructionalVideo).filter_by(program_id=p.id).first()
    users = users or {}
    if users.get("nurse") and not _get(db, ClinicStaff, clinic_id=clinic.id, user_id=users["nurse"].id):
        db.add(ClinicStaff(id=uuid.uuid4(), clinic_id=clinic.id, user_id=users["nurse"].id, can_manage=True,
                           can_publish=True, can_approve=True, can_view_clinical=True, created_at=now))
    emily = users.get("emily")
    if emily:
        if not db.query(CareEntitlement).filter_by(user_id=emily.id, program_id=p.id, revoked_at=None).first():
            db.add(CareEntitlement(id=uuid.uuid4(), user_id=emily.id, clinic_id=clinic.id, program_id=p.id,
                                   care_role="patient", source="staff_grant", terms_version="2026-11", created_at=now))
        if not db.query(CareDeviceAssignment).filter_by(user_id=emily.id, program_id=p.id, revoked_at=None).first():
            db.add(CareDeviceAssignment(id=uuid.uuid4(), clinic_id=clinic.id, program_id=p.id, user_id=emily.id,
                                        medication=MED, device=DEVICE, guide_lineage_id=guide.lineage_id if guide else None,
                                        video_id=video.id if video else None, verified_by=REVIEWER,
                                        source="assignment", is_demo=True, created_at=now))
    db.commit()
    return {"clinic": clinic.slug, "program": p.slug, "program_id": str(p.id), "clinic_id": str(clinic.id),
            "video_id": str(video.id) if video else None}
