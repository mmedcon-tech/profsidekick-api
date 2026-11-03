"""Care Parts 3-4: reply drafts + clinician approvals; patient memory, doctor guidance,
agent grants and access log.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _fk(name, table, nullable=False, ondelete="CASCADE", index=False):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable, index=index)


def upgrade():
    op.create_table("care_reply_drafts", _id(), _fk("clinic_id", "clinics", index=True),
                    _fk("handoff_id", "care_handoffs", index=True),
                    sa.Column("body", sa.Text(), nullable=False), sa.Column("body_sha256", sa.String(64), nullable=False),
                    sa.Column("state", sa.String(20), nullable=False, server_default="awaiting_review"),
                    _fk("author_user_id", "users", True, "SET NULL"), sa.Column("created_at", sa.DateTime()),
                    sa.Column("updated_at", sa.DateTime()), sa.Column("sent_at", sa.DateTime()),
                    _fk("sent_by", "users", True, "SET NULL"))
    op.create_table("care_clinician_approvals", _id(), _fk("clinic_id", "clinics", index=True),
                    sa.Column("subject_type", sa.String(20), nullable=False),
                    sa.Column("subject_id", UUID(as_uuid=True), nullable=False, index=True),
                    sa.Column("sha256", sa.String(64), nullable=False),
                    _fk("approver_user_id", "users", True, "SET NULL"),
                    sa.Column("approver_name", sa.String(255), nullable=False),
                    sa.Column("approved_at", sa.DateTime(), nullable=False))
    op.create_table("care_patient_memory", _id(), _fk("clinic_id", "clinics", index=True),
                    _fk("user_id", "users", index=True), sa.Column("key", sa.String(60), nullable=False),
                    sa.Column("value", sa.String(500), nullable=False), sa.Column("created_at", sa.DateTime()),
                    sa.Column("updated_at", sa.DateTime()),
                    sa.UniqueConstraint("clinic_id", "user_id", "key", name="uq_care_patient_memory"))
    op.create_table("care_doctor_guidance", _id(), _fk("clinic_id", "clinics", index=True),
                    sa.Column("persona_id", UUID(as_uuid=True)), sa.Column("text", sa.Text(), nullable=False),
                    sa.Column("status", sa.String(20), nullable=False, server_default="active"),
                    _fk("updated_by", "users", True, "SET NULL"), sa.Column("updated_at", sa.DateTime()))
    op.create_table("care_agent_grants", _id(), _fk("clinic_id", "clinics", index=True),
                    _fk("patient_user_id", "users", index=True), sa.Column("agent_label", sa.String(120), nullable=False),
                    sa.Column("scopes", JSONB(), nullable=False, server_default="[]"),
                    sa.Column("token_sha256", sa.String(64), nullable=False, unique=True),
                    sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime()),
                    sa.Column("created_at", sa.DateTime()), sa.Column("last_used_at", sa.DateTime()))
    op.create_table("care_agent_access_log", _id(), _fk("grant_id", "care_agent_grants", True, index=True),
                    _fk("patient_user_id", "users", True, index=True), _fk("clinic_id", "clinics", True),
                    sa.Column("tool", sa.String(60), nullable=False), sa.Column("outcome", sa.String(20), nullable=False),
                    sa.Column("reason", sa.String(60)), sa.Column("items", sa.Integer()),
                    sa.Column("created_at", sa.DateTime(), index=True))


def downgrade():
    for t in ("care_agent_access_log", "care_agent_grants", "care_doctor_guidance", "care_patient_memory",
              "care_clinician_approvals", "care_reply_drafts"):
        op.drop_table(t)
