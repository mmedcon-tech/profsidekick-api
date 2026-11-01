"""MYO'S Fertility: IVF Care program, persistent consultations, fertility
knowledge with retrieval metadata, instructional videos, patient context
with provenance, clinic protocols and simulated escalations."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

revision = "x6y7z8a9b0c1"
down_revision = "w5x6y7z8a9b0"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "care_programs",
        _id(),
        sa.Column("slug", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("doctor_config", JSONB),
        sa.Column("clinic_id", sa.String(100)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "care_program_memberships",
        _id(),
        sa.Column("program_id", UUID(as_uuid=True), sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("care_role", sa.String(20), nullable=False, server_default="patient"),
        sa.Column("treatment_stage", sa.String(50)),
        sa.Column("linked_patient_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("authorized_scopes", JSONB, nullable=False, server_default="[]"),
        sa.Column("joined_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("program_id", "user_id", name="uq_care_membership"),
    )
    op.create_table(
        "consultations",
        _id(),
        sa.Column("program_id", UUID(as_uuid=True), sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("care_role", sa.String(20), nullable=False, server_default="patient"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("last_mode", sa.String(10)),
        sa.Column("summary", sa.Text()),
        sa.Column("summarized_until", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_activity_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("program_id", "user_id", name="uq_consultation_user_program"),
    )
    op.create_table(
        "consultation_messages",
        _id(),
        sa.Column("consultation_id", UUID(as_uuid=True), sa.ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("sender", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False, server_default="text"),
        sa.Column("care_role", sa.String(20)),
        sa.Column("provenance", sa.String(30), nullable=False, server_default="patient_reported"),
        sa.Column("safety", JSONB),
        sa.Column("sources", JSONB),
        sa.Column("videos", JSONB),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), index=True),
    )
    op.create_table(
        "fertility_knowledge_documents",
        _id(),
        sa.Column("document_key", sa.String(120), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="general_education"),
        sa.Column("approval_status", sa.String(30), nullable=False, server_default="demo_unreviewed"),
        sa.Column("clinic_id", sa.String(100)),
        sa.Column("jurisdiction", sa.String(50)),
        sa.Column("clinician_approver", sa.String(255)),
        sa.Column("version", sa.String(30)),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("effective_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("original_reference", sa.String(500)),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "instructional_videos",
        _id(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("topic", sa.String(100)),
        sa.Column("treatment_stage", sa.String(50)),
        sa.Column("audience", sa.String(20), nullable=False, server_default="both"),
        sa.Column("medication_name", sa.String(120)),
        sa.Column("device_name", sa.String(120)),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("clinic_id", sa.String(100)),
        sa.Column("approval_status", sa.String(30), nullable=False, server_default="demo_unreviewed"),
        sa.Column("version", sa.String(30)),
        sa.Column("storage_uri", sa.String(500)),
        sa.Column("external_url", sa.String(1000)),
        sa.Column("content_type", sa.String(100)),
        sa.Column("thumbnail_uri", sa.String(500)),
        sa.Column("transcript", sa.Text()),
        sa.Column("captions_vtt", sa.Text()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("uploaded_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "fertility_knowledge_chunks",
        _id(),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("fertility_knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("video_id", UUID(as_uuid=True), sa.ForeignKey("instructional_videos.id", ondelete="CASCADE"), index=True),
        sa.Column("start_seconds", sa.Integer()),
        sa.Column("end_seconds", sa.Integer()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", JSONB, nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(1536)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "patient_context_entries",
        _id(),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("program_id", UUID(as_uuid=True), sa.ForeignKey("care_programs.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provenance", sa.String(30), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source", sa.String(255)),
        sa.Column("verified_by", sa.String(255)),
        sa.Column("effective_at", sa.DateTime()),
        sa.Column("consent_scope", sa.String(50), nullable=False, server_default="patient_only"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "clinic_protocols",
        _id(),
        sa.Column("clinic_id", sa.String(100), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("topic", sa.String(100)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.String(30), nullable=False, server_default="1"),
        sa.Column("approval_status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("clinician_approver", sa.String(255)),
        sa.Column("effective_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("knowledge_document_id", UUID(as_uuid=True), sa.ForeignKey("fertility_knowledge_documents.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "simulated_escalations",
        _id(),
        sa.Column("consultation_id", UUID(as_uuid=True), sa.ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    programs = sa.table(
        "care_programs",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_public", sa.Boolean),
        sa.column("clinic_id", sa.String),
    )
    op.bulk_insert(
        programs,
        [{
            "id": uuid.uuid4(),
            "slug": "ivf-care",
            "name": "IVF Care",
            "description": "Understand IVF, egg freezing, hormonal stimulation, injections, procedures and recovery with your AI Fertility Doctor.",
            "is_public": True,
            "clinic_id": "demo-harbor",
        }],
    )


def downgrade() -> None:
    for table in (
        "simulated_escalations",
        "clinic_protocols",
        "patient_context_entries",
        "fertility_knowledge_chunks",
        "instructional_videos",
        "fertility_knowledge_documents",
        "consultation_messages",
        "consultations",
        "care_program_memberships",
        "care_programs",
    ):
        op.drop_table(table)
