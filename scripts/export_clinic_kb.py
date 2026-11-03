"""Export a clinic's knowledge hub (documents, versions, sources, approval metadata) as JSON.
Usage: docker compose exec -T backend python -m scripts.export_clinic_kb <clinic-slug> > out.json"""
import json
import sys

from app.database import SessionLocal
from app.database.models import Clinic
from app.services.care.hub import export_clinic

db = SessionLocal()
clinic = db.query(Clinic).filter_by(slug=sys.argv[1]).first()
if not clinic:
    sys.exit("no such clinic")
json.dump(export_clinic(db, clinic, include_drafts="--drafts" in sys.argv), sys.stdout, indent=1)
