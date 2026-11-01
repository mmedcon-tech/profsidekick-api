"""Verify the real OpenAI path end-to-end WITHOUT printing the key.

1. Checks OPENAI_API_KEY in .env by shape only (missing / placeholder / present).
2. Optionally rebuilds + restarts the backend container (--rebuild) so the new key is loaded.
3. Runs one synthetic
   request through the real care path: signs in the synthetic demo patient
   (emily.demo, from the seed's credentials file) and asks an education question.
   PASS only if the reply is provenance=ai_generated with provider.llm=ok.

Usage:  .venv/bin/python scripts/verify_care_llm.py [--rebuild] [--base http://localhost:8000]
Exit code 0 = live LLM verified, 2 = key missing/placeholder, 1 = call failed (error kind printed).
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.care.health import key_state  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--rebuild", action="store_true")
ap.add_argument("--base", default="http://localhost:8000")
ap.add_argument("--creds", default="/tmp/fert/fertility_demo_users.json")
args = ap.parse_args()

val = ""
for line in (ROOT / ".env").read_text().splitlines():
    if line.startswith("OPENAI_API_KEY="):
        val = line.split("=", 1)[1]
state = key_state(val, "sk-")
del val
print(f"OPENAI_API_KEY in .env: {state}")
if state != "present":
    print("BLOCKED: paste a real key into profsidekick-api/.env (see docs/OPENAI_KEY_SETUP.md), then re-run with --rebuild.")
    sys.exit(2)

if args.rebuild:
    print("Rebuilding backend container …")
    subprocess.run(["docker", "compose", "up", "-d", "--build", "backend"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
for _ in range(60):
    try:
        if httpx.get(args.base + "/api/care/health", timeout=3).status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(2)
h = httpx.get(args.base + "/api/care/health", timeout=5).json()
llm = next(c for c in h["checks"] if c["service"] == "openai")
print(f"backend sees key: ok={llm['ok']} error_kind={llm['error_kind']}")
if not llm["ok"]:
    print("BLOCKED: the running backend still has no usable key — re-run with --rebuild.")
    sys.exit(2)

creds = json.loads(Path(args.creds).read_text())["emily"]
r = httpx.post(args.base + "/api/auth/login", json={"username": creds["username"], "password": creds["password"]})
b = r.json()
tok = b.get("access_token") or b.get("token") or (b.get("data") or {}).get("access_token")
hd = {"Authorization": f"Bearer {tok}"}
r = httpx.post(args.base + "/api/care/p/harbor-fertility-demo/ivf-medication-prep/messages", headers=hd,
               json={"content": "What should I check on my pen before I use it?"}, timeout=90)
rid = r.headers.get("x-request-id")
d = r.json()
prov = d["route"]["provider"]
print(f"request_id={rid} status={r.status_code} result={d['result']['type']} provenance={d['result']['provenance']} "
      f"llm={prov.get('llm')} error_kind={prov.get('error_kind')} sources={len(d['result']['sources'])}")
ok = d["result"]["provenance"] == "ai_generated" and prov.get("llm") == "ok"
print("PASS: live OpenAI answer through the care path" if ok else "FAIL")
sys.exit(0 if ok else 1)
