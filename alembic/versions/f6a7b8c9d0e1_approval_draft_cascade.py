"""Clinician approvals of reply drafts cascade with the draft (no orphaned approvals).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("care_clinician_approvals", sa.Column("draft_id", UUID(as_uuid=True), nullable=True))
    op.execute("DELETE FROM care_clinician_approvals WHERE subject_type = 'reply_draft' "
               "AND subject_id NOT IN (SELECT id FROM care_reply_drafts)")
    op.execute("UPDATE care_clinician_approvals SET draft_id = subject_id WHERE subject_type = 'reply_draft'")
    op.create_foreign_key("fk_care_clinician_approvals_draft", "care_clinician_approvals", "care_reply_drafts",
                          ["draft_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_care_clinician_approvals_draft_id", "care_clinician_approvals", ["draft_id"])


def downgrade():
    op.drop_index("ix_care_clinician_approvals_draft_id", table_name="care_clinician_approvals")
    op.drop_constraint("fk_care_clinician_approvals_draft", "care_clinician_approvals", type_="foreignkey")
    op.drop_column("care_clinician_approvals", "draft_id")
