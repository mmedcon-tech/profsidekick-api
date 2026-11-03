import re, json, hashlib
from docs import DOCS
urls=open("urls.txt").read().split()
def txt(n):
    try: return re.sub(r"\s+"," ",open(f"txt/{n}.txt",errors="ignore").read()).lower()
    except FileNotFoundError: return ""
bad=0; manifest=[]
for d in DOCS:
    srcs=" ".join(txt(n) for n in d["src"])
    for n in d["src"]:
        assert len(txt(n))>1000, (d["key"], n, "source not fetched")
    miss=[f for f in d["facts"] if re.sub(r"\s+"," ",f.lower()) not in srcs]
    if miss: bad+=1; print("MISSING", d["key"], miss)
    manifest.append({"key":d["key"],"sources":[urls[n-1] for n in d["src"]],"facts_verified":len(d["facts"])-len(miss)})
json.dump(manifest,open("manifest.json","w"),indent=1)
print(len(DOCS),"docs", bad,"with missing facts", sum(len(d["body"]) for d in DOCS),"chars")
