import os, sys, json, httpx
sys.path.insert(0, "/tmp/kb")
from docs import DOCS
urls = open("/tmp/kb/urls.txt").read().split()
from app.database import SessionLocal
from app.database.models import CareProgram, CareContentItem, Clinic
db = SessionLocal()
clinic = db.query(Clinic).filter_by(slug="myos-fertility-sf").first()
progs = {p.slug: str(p.id) for p in db.query(CareProgram).filter_by(clinic_ref_id=clinic.id).all()}
B = "http://localhost:8000"
pw = os.getenv("SEED_PASSWORD") or "12345678"
tok = httpx.post(f"{B}/api/auth/login", json={"username": "myos_publisher", "password": pw}).json()
h = {"Authorization": f"Bearer {tok.get('access_token') or tok.get('token')}"}
PUB = {"hfea.gov.uk": "HFEA", "reproductivefacts.org": "ASRM ReproductiveFacts", "eshre.eu": "ESHRE", "nhs.uk": "NHS", "acog.org": "ACOG"}
made = skipped = 0
for d in DOCS:
    primary = urls[d["src"][0] - 1]
    pub = next(v for k, v in PUB.items() if k in primary)
    refs = "; ".join(urls[n - 1] for n in d["src"])
    body = d["body"] + f"\n\n## Sources\nWritten in plain language by the clinic team from: {refs} (fetched 3 Nov 2026). Not personal medical advice."
    for slug in d["progs"]:
        pid = progs[slug]
        if db.query(CareContentItem).filter(CareContentItem.program_id == pid, CareContentItem.title == d["title"],
                                            CareContentItem.status.in_(("draft", "in_review", "approved"))).first():
            skipped += 1; continue
        r = httpx.post(f"{B}/api/care/studio/programs/{pid}/content/upload", headers=h,
                       files={"file": (f"{d['key']}.md", body.encode(), "text/markdown")},
                       data={"title": d["title"], "kind": "document", "audience": "patient", "language": "en",
                             "source": f"{pub}: {d['title']}"}, timeout=60)
        r.raise_for_status(); iid = r.json()["id"]
        r = httpx.patch(f"{B}/api/care/studio/content/{iid}", headers=h, json={"source_url": primary}, timeout=60); r.raise_for_status()
        for act in ("submit", "pin_for_pilot"):
            r = httpx.post(f"{B}/api/care/studio/content/{iid}/{act}", headers=h, json={}, timeout=120); r.raise_for_status()
        made += 1
        print(slug, r.json()["status_label"], d["key"])
print("made", made, "skipped", skipped)
