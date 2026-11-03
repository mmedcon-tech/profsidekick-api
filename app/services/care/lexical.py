"""BM25 keyword ranking for clinic content, used when embeddings are unavailable and blended with them when not.

Light stemming plus a small fertility synonym table, so "egg retrieval" finds "egg collection", "OHSS" finds
"hyperstimulation", and the passage whose heading names the topic outranks passages that mention it in passing.
"""
from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Sequence, Tuple

STOP = set("""a an and are as at be been being but by can could did do does doing for from had has have how i if in into is
it its me my of on or our should so than that the their them then there these they this to too us was we were what when
where which who why will with would you your yours am about after again all any because before between both during each
few further here just more most no nor not only other own same some such very s t don now ivf""".split())
# "ivf" is in nearly every passage of an IVF knowledge base, so it carries no ranking signal.

SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "retrieval": ("collection", "aspiration"), "retrieve": ("collection",), "pick": ("collection",),
    "collection": ("retrieval",), "ohss": ("hyperstimulation",), "hyperstimulation": ("ohss",),
    "icsi": ("intracytoplasmic",), "pgt": ("preimplantation", "genetic"), "fet": ("frozen", "transfer"),
    "tww": ("two", "week", "wait"), "luteal": ("progesterone",), "progesterone": ("luteal",),
    "price": ("cost",), "expensive": ("cost",), "afford": ("cost",), "pay": ("cost",), "insurance": ("cost", "funding"),
    "chance": ("success",), "odds": ("success",), "rate": ("success",), "sad": ("emotional", "counselling"),
    "anxious": ("stress", "emotional"), "anxiety": ("stress",), "depressed": ("emotional", "counselling"),
    "sperm": ("semen",), "semen": ("sperm",), "embryologist": ("embryo",), "blast": ("blastocyst",),
    "day5": ("blastocyst",), "freeze": ("freezing", "vitrification"), "frozen": ("freezing",),
    "trigger": ("hcg",), "shot": ("injection",), "jab": ("injection",), "womb": ("uterus",), "uterus": ("womb",),
    "fail": ("unsuccessful",), "failed": ("unsuccessful",), "negative": ("unsuccessful",), "didn": ("unsuccessful",),
    "weight": ("bmi",), "bmi": ("weight",), "smoke": ("smoking",), "drink": ("alcohol",), "coffee": ("caffeine",),
    "donated": ("donor",), "donation": ("donor",), "addon": ("add",), "glossary": ("term",), "mean": ("term",),
    "aneuploidy": ("pgt",), "genetic": ("pgt",), "grading": ("grade",), "grade": ("grading",),
}


def stem(w: str) -> str:
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: len(w) - len(suf)] + rep
    return w


def tokens(text: str) -> List[str]:
    return [stem(w) for w in re.findall(r"[0-9a-z\u0600-\u06ff]+", (text or "").lower().replace("-", " "))
            if w not in STOP and (len(w) >= 3 or w.isdigit() or w in ("hcg",))]


def query_terms(q: str) -> Dict[str, float]:
    """Query term -> weight (1.0 for the user's words, 0.5 for synonyms)."""
    out: Dict[str, float] = {}
    raw = re.findall(r"[0-9a-z]+", (q or "").lower().replace("-", " "))
    for w in raw:
        if w in STOP:
            continue
        t = stem(w)
        if len(t) >= 3 or t.isdigit():
            out[t] = 1.0
        for s in SYNONYMS.get(w, ()) + SYNONYMS.get(t, ()):
            out.setdefault(stem(s), 0.5)
    return out


def bm25(query: str, docs: Sequence[str], k1: float = 1.2, b: float = 0.75) -> List[float]:
    """BM25 per doc. The first line of each doc (title/heading) counts twice."""
    q = query_terms(query)
    if not q or not docs:
        return [0.0] * len(docs)
    toks = []
    for d in docs:
        first, _, rest = (d or "").partition("\n")
        toks.append(tokens(first) * 2 + tokens(rest))
    n = len(toks)
    avg = sum(len(t) for t in toks) / n or 1.0
    df: Dict[str, int] = {}
    for t in toks:
        for w in set(t):
            if w in q:
                df[w] = df.get(w, 0) + 1
    scores = []
    for t in toks:
        tf: Dict[str, int] = {}
        for w in t:
            if w in q:
                tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w, f in tf.items():
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += q[w] * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(t) / avg))
        scores.append(s)
    return scores


def coverage(query: str, doc: str) -> float:
    """Share of the user's own (weight 1.0) terms found in the doc, 0..1."""
    q = [w for w, wt in query_terms(query).items() if wt == 1.0]
    if not q:
        return 0.0
    d = set(tokens(doc))
    return sum(1 for w in q if w in d) / len(q)
