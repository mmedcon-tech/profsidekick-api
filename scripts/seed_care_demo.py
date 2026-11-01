"""Seed fictional Demo Clinic A / B care programs (idempotent). Usage:
    python scripts/seed_care_demo.py [--staff USERNAME ...]
--staff gives the named users full staff permissions in both demo clinics."""
import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.connection import SessionLocal  # noqa: E402
from app.database.models import Clinic, ClinicStaff, User  # noqa: E402
from app.services.care.seed import CLINICS, seed_demo  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--staff", nargs="*", default=[])
args = ap.parse_args()
db = SessionLocal()
print(seed_demo(db))
for name in args.staff:
    u = db.query(User).filter_by(username=name).first()
    if not u:
        print("no such user:", name)
        continue
    for slug in CLINICS:
        c = db.query(Clinic).filter_by(slug=slug).first()
        if not db.query(ClinicStaff).filter_by(clinic_id=c.id, user_id=u.id).first():
            db.add(ClinicStaff(id=uuid.uuid4(), clinic_id=c.id, user_id=u.id, can_manage=True, can_publish=True,
                               can_approve=True, can_view_clinical=True, created_at=datetime.utcnow()))
    db.commit()
    print("staff:", name)
