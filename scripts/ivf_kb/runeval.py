import sys, json, time, asyncio, re
sys.path.insert(0, "/tmp/kb")
from docs import DOCS
from evalset import EVAL
from datetime import datetime
from app.database import SessionLocal
from app.database.models import User, Clinic, CareProgram, ConsultationMessage
from app.services.care import access, chat, content
mode = sys.argv[1] if len(sys.argv) > 1 else "retrieval"
T = {d["key"]: d["title"] for d in DOCS}
db = SessionLocal()
u = db.query(User).filter(User.email.ilike("sofia%")).first()
cl = db.query(Clinic).filter_by(slug="myos-fertility-sf").first()
p = db.query(CareProgram).filter_by(clinic_ref_id=cl.id, slug="ivf-care").first()
a = access.require_program_access(db, u, p)
courses = content.visible_course_ids(db, a)
started = datetime.utcnow()
rows = []; r_hit = r_n = g_pass = g_n = c_pass = c_n = 0; lat = []
for q, exp in EVAL:
    row = {"q": q, "exp": exp}
    if exp != ["CARE"]:
        hits = content.retrieve(db, program_id=p.id, clinic_id=cl.id, visible_course_ids=courses, audience="patient", query=q)
        titles = [h["title"] for h in hits[:3]]
        ok = any(T[k] in titles for k in exp); r_n += 1; r_hit += ok
        row.update(top3=titles, retrieval_hit=ok)
    if mode == "live":
        t = time.time(); res = asyncio.run(chat.send(db, u, cl, a, q)); dt = time.time() - t; lat.append(dt)
        res = res.get("result", res); txt = res.get("text") or ""
        srcs = [s.get("title") for s in res.get("sources") or []]
        row.update(latency=round(dt, 2), type=res.get("type"), prov=res.get("provenance"), cited=srcs, text=txt[:300])
        if exp == ["CARE"]:
            c_n += 1
            ok = res.get("type") in ("needs_clinician", "urgent_contact_path") or bool(res.get("handoff_offered"))
            c_pass += ok; row["care_routed"] = ok
        else:
            g_n += 1
            ok = res.get("type") == "education" and res.get("provenance") == "ai_generated" and bool(srcs) \
                 and bool(re.search(r"\[\d+\]", txt)) and any(T[k] in srcs for k in exp)
            g_pass += ok; row["grounded"] = ok
    rows.append(row)
summary = {"retrieval_top3_hit": f"{r_hit}/{r_n}"}
if mode == "live":
    lat.sort()
    summary.update(grounded=f"{g_pass}/{g_n}", care_routed=f"{c_pass}/{c_n}",
                   latency_p50=round(lat[len(lat)//2], 2), latency_p95=round(lat[int(len(lat)*.95)-1], 2), latency_max=round(lat[-1], 2),
                   over_5s=sum(1 for x in lat if x > 5))
    summary["eval_started_utc"] = started.isoformat()
json.dump({"summary": summary, "rows": rows}, open(f"/tmp/kb/eval_{mode}.json", "w"), indent=1)
print(json.dumps(summary))
for r in rows:
    if r.get("retrieval_hit") is False or r.get("grounded") is False or r.get("care_routed") is False:
        print("FAIL", json.dumps(r)[:600])
