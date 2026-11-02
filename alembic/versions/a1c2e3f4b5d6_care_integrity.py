"""care integrity: content SHA-256 pins, chunk hash tags, invitation verifier algorithm

Revision ID: a1c2e3f4b5d6
Revises: z8a9b0c1d2e3

Upgrade backfills: approved items get content_sha256 = approved_sha256 = the
canonical hash of their current row; their chunks are tagged with it (they
were indexed from that same row). Draft/in_review items get content_sha256
only. Existing invitations keep their plain SHA-256 verifier and are marked
hash_alg='sha256' (legacy, still redeemable until expiry); new ones use HMAC.
Downgrade drops the columns only (no data in other columns is touched).
"""
import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "a1c2e3f4b5d6"
down_revision = "z8a9b0c1d2e3"
branch_labels = None
depends_on = None

FIELDS = ("title", "body", "kind", "language", "audience", "applicability", "course_id", "video_id")


def _hash(row) -> str:
    # must stay identical to app.services.care.integrity.content_hash
    doc = {f: (str(row[f]) if row[f] is not None else None) for f in FIELDS}
    raw = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upgrade():
    op.add_column("care_content_items", sa.Column("content_sha256", sa.String(64), nullable=True))
    op.add_column("care_content_items", sa.Column("approved_sha256", sa.String(64), nullable=True))
    op.add_column("care_content_chunks", sa.Column("item_sha256", sa.String(64), nullable=True))
    op.add_column("care_invitations", sa.Column("hash_alg", sa.String(16), nullable=False, server_default="sha256"))
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"SELECT id, status, {', '.join(FIELDS)} FROM care_content_items")).mappings().all()
    for r in rows:
        h = _hash(r)
        if r["status"] == "approved":
            conn.execute(sa.text("UPDATE care_content_items SET content_sha256=:h, approved_sha256=:h WHERE id=:id"),
                         {"h": h, "id": r["id"]})
            conn.execute(sa.text("UPDATE care_content_chunks SET item_sha256=:h WHERE item_id=:id"), {"h": h, "id": r["id"]})
        else:
            conn.execute(sa.text("UPDATE care_content_items SET content_sha256=:h WHERE id=:id"), {"h": h, "id": r["id"]})
            # non-approved items must have no retrievable chunks
            conn.execute(sa.text("DELETE FROM care_content_chunks WHERE item_id=:id"), {"id": r["id"]})


def downgrade():
    op.drop_column("care_invitations", "hash_alg")
    op.drop_column("care_content_chunks", "item_sha256")
    op.drop_column("care_content_items", "approved_sha256")
    op.drop_column("care_content_items", "content_sha256")
