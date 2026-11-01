"""care phase 3: review queue, invitations, supporter grants, device assignments, video transcripts

Revision ID: z8a9b0c1d2e3
Revises: y7z8a9b0c1d2
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "z8a9b0c1d2e3"
down_revision = "y7z8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade():
    for name, col in [
        ("idempotency_key", sa.Column("idempotency_key", sa.String(80), nullable=True)),
        ("received_at", sa.Column("received_at", sa.DateTime(), nullable=True)),
        ("assigned_to", sa.Column("assigned_to", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)),
        ("acknowledged_at", sa.Column("acknowledged_at", sa.DateTime(), nullable=True)),
        ("closed_at", sa.Column("closed_at", sa.DateTime(), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(), nullable=True)),
    ]:
        op.add_column("care_handoffs", col)
    op.execute("UPDATE care_handoffs SET received_at = created_at WHERE received_at IS NULL")
    op.create_index("uq_care_handoffs_user_idem", "care_handoffs", ["user_id", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.create_table(
        "care_handoff_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("handoff_id", UUID(as_uuid=True), sa.ForeignKey("care_handoffs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "care_invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("code_hint", sa.String(8), nullable=True),
        sa.Column("clinic_id", UUID(as_uuid=True), sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("program_id", UUID(as_uuid=True), sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("care_role", sa.String(20), nullable=False, server_default="patient"),
        sa.Column("scopes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("patient_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "care_support_grants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("clinic_id", UUID(as_uuid=True), sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("program_id", UUID(as_uuid=True), sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("patient_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("supporter_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("invitation_id", UUID(as_uuid=True), sa.ForeignKey("care_invitations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entitlement_id", UUID(as_uuid=True), sa.ForeignKey("care_entitlements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scopes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "care_device_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("clinic_id", UUID(as_uuid=True), sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("program_id", UUID(as_uuid=True), sa.ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("medication", sa.String(120), nullable=False),
        sa.Column("device", sa.String(120), nullable=True),
        sa.Column("guide_lineage_id", UUID(as_uuid=True), nullable=True),
        sa.Column("video_id", UUID(as_uuid=True), sa.ForeignKey("instructional_videos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("verified_by", sa.String(255), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.add_column("care_content_items", sa.Column(
        "video_id", UUID(as_uuid=True), sa.ForeignKey("instructional_videos.id", ondelete="CASCADE"), nullable=True))


def downgrade():
    op.drop_column("care_content_items", "video_id")
    op.drop_table("care_device_assignments")
    op.drop_table("care_support_grants")
    op.drop_table("care_invitations")
    op.drop_table("care_handoff_events")
    op.drop_index("uq_care_handoffs_user_idem", table_name="care_handoffs")
    for c in ("updated_at", "closed_at", "acknowledged_at", "assigned_to", "received_at", "idempotency_key"):
        op.drop_column("care_handoffs", c)
