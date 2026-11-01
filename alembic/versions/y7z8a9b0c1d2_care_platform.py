"""Care platform: clinics, staff, program templates, personas, courses,
lessons, explicit entitlements, versioned content, red flags, handoffs.

Data migration (no access broadening):
  * the legacy free-text clinic key on care_programs becomes a Clinic row;
  * each CareProgramMembership becomes one program-level CareEntitlement
    (source=legacy_membership, same care_role). Memberships are kept, so
    downgrade loses nothing.
  * the legacy ivf-care program keeps its self-join behaviour
    (enrollment_policy=open) because it was already open; all other
    programs default to staff-granted access.
  * three launch ProgramTemplates are inserted as DATA only.
  * avatar subscriptions are NOT converted into care entitlements.

Revision ID: y7z8a9b0c1d2
Revises: x6y7z8a9b0c1
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "y7z8a9b0c1d2"
down_revision = "x6y7z8a9b0c1"
branch_labels = None
depends_on = None

U = UUID(as_uuid=True)


def _id():
    return sa.Column("id", U, primary_key=True)


def _ts(name="created_at"):
    return sa.Column(name, sa.DateTime, nullable=True)


LAUNCH_TEMPLATES = [
    ("fertility", "Fertility", "Reproductive medicine",
     "Education and between-visit questions for fertility treatment."),
    ("plastic-surgery", "Plastic surgery", "Aesthetic and reconstructive surgery",
     "Procedure courses (for example fat transfer, dermal fillers) with preparation and recovery guidance."),
    ("weight-management", "Weight management", "Metabolic health",
     "Weight-management education, including GLP-1 medicine education approved by the clinic."),
]


def upgrade():
    op.create_table("clinics", _id(),
        sa.Column("slug", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("branding", JSONB),
        sa.Column("contact_routes", JSONB, nullable=False, server_default="[]"),
        sa.Column("response_expectation", sa.Text),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_by", U, sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts(), _ts("updated_at"))
    op.create_table("clinic_staff", _id(),
        sa.Column("clinic_id", U, sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", U, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("can_manage", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("can_publish", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("can_approve", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("can_view_clinical", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("display_name", sa.String(255)),
        _ts(), sa.UniqueConstraint("clinic_id", "user_id", name="uq_clinic_staff"))
    op.create_table("program_templates", _id(),
        sa.Column("slug", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("care_area", sa.String(120)),
        sa.Column("description", sa.Text),
        sa.Column("default_config", JSONB),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", U, sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts())
    op.create_table("doctor_personas", _id(),
        sa.Column("clinic_id", U, sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255)), sa.Column("specialty", sa.String(255)),
        sa.Column("prompt", sa.Text),
        sa.Column("avatar_id", U, sa.ForeignKey("avatars.id", ondelete="SET NULL")),
        sa.Column("liveavatar_avatar_id", sa.String(100)), sa.Column("variant", sa.String(100)),
        sa.Column("voice_id", sa.String(100)), sa.Column("gender", sa.String(10)),
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        _ts(), _ts("updated_at"))
    for col in [
        sa.Column("clinic_ref_id", U, sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True),
        sa.Column("template_id", U, sa.ForeignKey("program_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("persona_id", U, sa.ForeignKey("doctor_personas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="published"),
        sa.Column("enrollment_policy", sa.String(20), nullable=False, server_default="staff"),
        sa.Column("branding", JSONB, nullable=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default="false"),
    ]:
        op.add_column("care_programs", col)
    op.create_index("ix_care_programs_clinic_ref_id", "care_programs", ["clinic_ref_id"])
    op.create_table("care_courses", _id(),
        sa.Column("program_id", U, sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("requires_entitlement", sa.Boolean, nullable=False, server_default="false"),
        _ts(), _ts("updated_at"), sa.UniqueConstraint("program_id", "slug", name="uq_care_course_slug"))
    op.create_table("care_lessons", _id(),
        sa.Column("course_id", U, sa.ForeignKey("care_courses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        _ts(), _ts("updated_at"))
    for col in [
        sa.Column("program_id", U, sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("course_id", U, sa.ForeignKey("care_courses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lesson_id", U, sa.ForeignKey("care_lessons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reviewer", sa.String(255), nullable=True),
        sa.Column("approved_at", sa.DateTime, nullable=True),
    ]:
        op.add_column("instructional_videos", col)
    op.create_index("ix_instructional_videos_program_id", "instructional_videos", ["program_id"])
    op.create_table("care_entitlements", _id(),
        sa.Column("user_id", U, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("clinic_id", U, sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("program_id", U, sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("course_id", U, sa.ForeignKey("care_courses.id", ondelete="CASCADE")),
        sa.Column("care_role", sa.String(20), nullable=False, server_default="patient"),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("granted_by", U, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("terms_version", sa.String(30)),
        _ts(), sa.Column("revoked_at", sa.DateTime))
    op.create_table("care_content_items", _id(),
        sa.Column("lineage_id", U, nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("clinic_id", U, sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("program_id", U, sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("course_id", U, sa.ForeignKey("care_courses.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("audience", sa.String(20), nullable=False, server_default="patient"),
        sa.Column("applicability", sa.Text), sa.Column("source", sa.String(500)),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("reviewer", sa.String(255)),
        sa.Column("approved_by", U, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime), sa.Column("expires_at", sa.DateTime),
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_by", U, sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts(), _ts("updated_at"))
    op.create_table("care_content_chunks", _id(),
        sa.Column("item_id", U, sa.ForeignKey("care_content_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536)))
    op.create_table("red_flag_rules", _id(),
        sa.Column("clinic_id", U, sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("program_id", U, sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("course_id", U, sa.ForeignKey("care_courses.id", ondelete="SET NULL")),
        sa.Column("symptom", sa.String(255), nullable=False),
        sa.Column("match_terms", JSONB, nullable=False, server_default="[]"),
        sa.Column("clinic_action", sa.Text, nullable=False),
        sa.Column("urgency", sa.String(20), nullable=False),
        sa.Column("contact_route", sa.String(100)), sa.Column("applicability", sa.Text),
        sa.Column("reviewer", sa.String(255)), sa.Column("review_date", sa.DateTime),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default="false"),
        _ts(), _ts("updated_at"))
    op.create_table("care_handoffs", _id(),
        sa.Column("clinic_id", U, sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("program_id", U, sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", U, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("consultation_id", U, sa.ForeignKey("consultations.id", ondelete="SET NULL")),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("contact_route", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("simulated", sa.Boolean, nullable=False, server_default="true"),
        _ts())

    # ── data ──
    conn = op.get_bind()
    now = datetime.utcnow()
    tpl_ids = {}
    for slug, name, area, desc in LAUNCH_TEMPLATES:
        tid = uuid.uuid4()
        tpl_ids[slug] = tid
        conn.execute(sa.text("INSERT INTO program_templates (id, slug, name, care_area, description, status, created_at) "
                             "VALUES (:i,:s,:n,:a,:d,'active',:t)"), dict(i=tid, s=slug, n=name, a=area, d=desc, t=now))
    keys = [r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT clinic_id FROM care_programs WHERE clinic_id IS NOT NULL")).fetchall()]
    for key in keys:
        cid = uuid.uuid4()
        conn.execute(sa.text(
            "INSERT INTO clinics (id, slug, name, description, contact_routes, response_expectation, status, is_demo, created_at, updated_at) "
            "VALUES (:i,:s,:n,:d,'[]',:r,'active',true,:t,:t)"),
            dict(i=cid, s=key, n=key.replace("-", " ").title() + " (fictional demo clinic)",
                 d="Fictional clinic created from the legacy demo program.",
                 r="This demo clinic is not staffed. Nothing you send here reaches a real care team.", t=now))
        conn.execute(sa.text("UPDATE care_programs SET clinic_ref_id=:c, is_demo=true WHERE clinic_id=:k"), dict(c=cid, k=key))
    # legacy ivf-care was self-join already; keep exactly that, nothing wider
    conn.execute(sa.text("UPDATE care_programs SET enrollment_policy='open', template_id=:t WHERE slug='ivf-care'"),
                 dict(t=tpl_ids["fertility"]))
    conn.execute(sa.text(
        "INSERT INTO care_entitlements (id, user_id, clinic_id, program_id, care_role, source, created_at) "
        "SELECT gen_random_uuid(), m.user_id, p.clinic_ref_id, m.program_id, m.care_role, 'legacy_membership', COALESCE(m.joined_at, now()) "
        "FROM care_program_memberships m JOIN care_programs p ON p.id=m.program_id WHERE p.clinic_ref_id IS NOT NULL"))


def downgrade():
    for t in ["care_handoffs", "red_flag_rules", "care_content_chunks", "care_content_items", "care_entitlements"]:
        op.drop_table(t)
    op.drop_index("ix_instructional_videos_program_id", table_name="instructional_videos")
    for c in ["approved_at", "reviewer", "position", "status", "lesson_id", "course_id", "program_id"]:
        op.drop_column("instructional_videos", c)
    op.drop_table("care_lessons")
    op.drop_table("care_courses")
    op.drop_index("ix_care_programs_clinic_ref_id", table_name="care_programs")
    for c in ["is_demo", "position", "branding", "enrollment_policy", "status", "persona_id", "template_id", "clinic_ref_id"]:
        op.drop_column("care_programs", c)
    op.drop_table("doctor_personas")
    op.drop_table("program_templates")
    op.drop_table("clinic_staff")
    op.drop_table("clinics")
