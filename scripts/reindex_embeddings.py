"""Rebuild care content vectors for the active embedding model (run after changing it in
app/services/ai/providers.json). Usage: python -m scripts.reindex_embeddings [clinic-slug] [--force]"""
import json
import sys

from app.database import SessionLocal
from app.database.models import Clinic
from app.services.care.hub import reindex

db = SessionLocal()
args = [a for a in sys.argv[1:] if not a.startswith("--")]
clinic = db.query(Clinic).filter_by(slug=args[0]).first() if args else None
print(json.dumps(reindex(db, clinic, force="--force" in sys.argv)))
