"""Embed every care / fertility knowledge chunk that has no embedding yet (e.g. indexed while OpenAI was
unavailable). Safe to re-run; touches only rows with embedding IS NULL and never changes text or hashes.

    docker compose exec -T backend python -m scripts.backfill_embeddings
"""
from app.database import SessionLocal
from app.database.models import CareContentChunk, FertilityKnowledgeChunk
from app.services.fertility.knowledge import _try_embed


def backfill(db, batch: int = 128) -> dict:
    out = {}
    for model in (CareContentChunk, FertilityKnowledgeChunk):
        done = 0
        while True:
            rows = db.query(model).filter(model.embedding.is_(None)).limit(batch).all()
            if not rows:
                break
            vecs = _try_embed([r.content for r in rows])
            if not vecs:
                out["stopped"] = "embeddings unavailable; re-run later"
                break
            for r, v in zip(rows, vecs):
                r.embedding = v
            db.commit()
            done += len(rows)
        out[model.__tablename__] = done
        if "stopped" in out:
            break
    return out


if __name__ == "__main__":
    db = SessionLocal()
    try:
        print(backfill(db))
    finally:
        db.close()
