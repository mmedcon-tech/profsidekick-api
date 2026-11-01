"""Seed the fictional Harbor Fertility demo (Emily, Jake, a synthetic nurse).
Idempotent. Synthetic accounts only; their passwords are generated and written
to a 0600 JSON file OUTSIDE the repo (default /tmp/fert/fertility_demo_users.json).

    python scripts/seed_fertility_demo.py [--out PATH]
"""
import argparse
import json
import os
import secrets
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.connection import SessionLocal  # noqa: E402
from app.database.models import User  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.care.seed_fertility import seed  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="/tmp/fert/fertility_demo_users.json")
args = ap.parse_args()
db = SessionLocal()
out = Path(args.out)
creds = json.loads(out.read_text()) if out.exists() else {}
people = {"emily": ("emily.demo", "Emily", "Carter (demo, 34)"), "jake": ("jake.demo", "Jake", "Carter (demo)"),
          "nurse": ("nurse.rosa.demo", "Rosa", "Nurse (synthetic demo)")}
users = {}
auth = AuthService.__new__(AuthService)
for key, (username, first, last) in people.items():
    u = db.query(User).filter_by(username=username).first()
    if not u or key not in creds:
        pw = creds.get(key, {}).get("password") or ("Demo-" + secrets.token_urlsafe(12))
        if not u:
            u = User(id=uuid.uuid4(), username=username, email=f"{username}@example.invalid", first_name=first,
                     last_name=last, role="subscriber", email_verified=True, is_approved=True,
                     created_at=datetime.utcnow(), updated_at=datetime.utcnow(), password_hash="")
            db.add(u)
        u.password_hash = auth.hash_password(pw)
        creds[key] = {"username": username, "password": pw}
    users[key] = u
db.commit()
info = seed(db, users)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({**creds, "_info": info}, indent=1))
os.chmod(out, 0o600)
print(json.dumps(info), "| credentials written to", out)
