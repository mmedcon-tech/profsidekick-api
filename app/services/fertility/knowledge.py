"""
Fertility knowledge: parse the IVF Doctor Twin KB into question-level chunks
with the KB §11 metadata, index instructional-video transcripts as timestamped
segments, and retrieve with backend source filtering.

Phase 1 (default, FERTILITY_KNOWLEDGE_PHASE=1): general LLM + RAG; demo
(unreviewed) and approved sources are both retrievable.
Phase 2 (FERTILITY_KNOWLEDGE_PHASE=2): only approval_status == "approved"
sources are retrievable and the answer must come from them; if nothing
approved matches, the consultation says so instead of calling the LLM.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.database.models import FertilityKnowledgeChunk, FertilityKnowledgeDocument, InstructionalVideo

logger = logging.getLogger(__name__)

KB_PATH = Path(__file__).resolve().parents[3] / "knowledge" / "ivf_doctor_twin_kb.md"
KB_DOCUMENT_KEY = "myos-ivf-doctor-twin-kb-v1"
KB_TITLE = "MYO'S IVF Doctor Twin Knowledge Base v1.0"
DEMO_CLINIC = "demo-harbor"

CATEGORIES = [
    "ivf_fundamentals", "fertility_evaluation", "hormonal_stimulation", "fertility_injections",
    "medication_storage", "missed_or_incorrect_doses", "follicle_monitoring", "trigger_injections",
    "egg_retrieval", "sperm_collection", "fertilization_embryo_development", "embryo_transfer",
    "progesterone_support", "pregnancy_testing", "egg_freezing", "side_effects_complications",
    "ohss_warning_signs", "emotional_wellbeing", "partner_support", "recovery_aftercare",
    "clinic_communication", "patient_history",
]

_TOPIC_RULES = [
    ("ohss_warning_signs", r"swollen|swelling|urinat|ohss"),
    ("missed_or_incorrect_doses", r"missed|late|wrong|double|repeat|half|leak|not sure how much|partial|pulled out|malfunction|dropped"),
    ("medication_storage", r"unrefrigerated|storage of medication|refrigerat|fridge"),
    ("trigger_injections", r"trigger"),
    ("progesterone_support", r"progesterone|luteal"),
    ("pregnancy_testing", r"home test|hcg|pregnancy test|blood test"),
    ("embryo_transfer", r"transfer"),
    ("fertilization_embryo_development", r"fertiliz|embryo|icsi"),
    ("egg_freezing", r"freez|stored eggs|storage"),
    ("egg_retrieval", r"retrieval|anesthesia|sedation"),
    ("follicle_monitoring", r"follicle|estradiol|ultrasound|monitoring"),
    ("fertility_injections", r"inject|needle|syringe|pen|vial|dose"),
    ("hormonal_stimulation", r"stimulation|hormone|protocol"),
    ("fertility_evaluation", r"amh|afc|fsh|evaluation|alternatives"),
    ("side_effects_complications", r"pain|bleed|fever|nausea|bruise|allerg|faint|breath"),
    ("emotional_wellbeing", r"feel|guilty|cope|afraid|alone|cries|emotional|failed"),
    ("clinic_communication", r"clinic|nurse|team|employer|records"),
]

_STAGE_RULES = [
    ("transfer", r"transfer|hcg|home test|progesterone|spotting"),
    ("trigger_retrieval", r"trigger|retrieval|anesthesia|sedation"),
    ("egg_freezing", r"freez|stored eggs"),
    ("stimulation", r"stimulation|inject|dose|follicle|estradiol|bloating|pen|needle"),
    ("evaluation", r"amh|afc|fsh|protocol chosen|alternatives|before treatment"),
]


def knowledge_phase() -> int:
    try:
        return 2 if int(os.getenv("FERTILITY_KNOWLEDGE_PHASE", "1")) >= 2 else 1
    except ValueError:
        return 1


def allowed_approval_statuses(phase: Optional[int] = None) -> set:
    return {"approved"} if (phase or knowledge_phase()) == 2 else {"approved", "demo_unreviewed"}


def _topic(text: str) -> str:
    t = text.lower()
    for name, pat in _TOPIC_RULES:
        if re.search(pat, t):
            return name
    return "ivf_fundamentals"


def _stage(text: str) -> Optional[str]:
    t = text.lower()
    for name, pat in _STAGE_RULES:
        if re.search(pat, t):
            return name
    return None


def _risk(text: str) -> str:
    from app.services.fertility.safety import classify, EMERGENCY, CRISIS, MEDICATION, GENERAL

    c = classify(text).category
    if c in (EMERGENCY, CRISIS):
        return "emergency"
    if c == MEDICATION:
        return "urgent"
    return "education" if c == GENERAL else "routine"


@dataclass
class KBChunk:
    content: str
    meta: Dict[str, Any] = field(default_factory=dict)


_SECTION = re.compile(r"^(\d{1,2})\. (\S.*)$")
_QUESTION = re.compile(r"^(\d{2})\. (.+)$")


def _sections(text: str) -> List[tuple]:
    out, current = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _SECTION.match(line)
        expected = (current[0] + 1) if current else 1
        if m and not line.startswith("0") and int(m.group(1)) == expected:
            current = [int(m.group(1)), m.group(2), []]
            out.append(current)
        elif current is not None:
            current[2].append(line)
    return out


def _base_meta(section_no: int, section_title: str, **kw) -> Dict[str, Any]:
    source_type = "synthetic_demo" if section_no in (8, 9) else "general_education"
    meta = {
        "document_id": KB_DOCUMENT_KEY,
        "document_title": KB_TITLE,
        "section": f"{section_no}. {section_title}",
        "question_id": None,
        "audience": "both",
        "treatment_stage": None,
        "topic": None,
        "risk_level": "education",
        "source_type": source_type,
        "clinic_id": DEMO_CLINIC,
        "patient_id_if_applicable": None,
        "jurisdiction": None,
        "clinician_approver": None,
        "approval_status": "demo_unreviewed",
        "effective_at": "2026-11-01",
        "reviewed_at": None,
        "expires_at": None,
        "version": "1.0",
        "citation_label": f"IVF KB §{section_no} {section_title}",
        "escalation_route": None,
        "permitted_channels": ["avatar", "voice", "text", "whatsapp"],
        # §1-3 and §11-13 are operating rules for the system, not patient education.
        "consent_scope": "internal" if section_no in INTERNAL_SECTIONS else "public",
    }
    meta.update(kw)
    return meta


INTERNAL_SECTIONS = {1, 2, 3, 11, 12, 13}
# Bump when chunking or metadata rules change so startup re-indexes.
PARSER_VERSION = "2"


def kb_digest(text: str) -> str:
    return hashlib.sha256(f"{PARSER_VERSION}\n{text}".encode("utf-8")).hexdigest()


def parse_kb(text: str) -> List[KBChunk]:
    """Split the KB by section and question, preserving §11 metadata."""
    chunks: List[KBChunk] = []
    for no, title, lines in _sections(text):
        if no in (5, 6):
            audience = "patient" if no == 5 else "partner"
            prefix = "P" if no == 5 else "R"
            group = None
            for line in lines:
                q = _QUESTION.match(line)
                if not q:
                    group = line
                    continue
                gid = re.sub(r"[^A-Z]", "", "".join(w[0] for w in (group or "X").upper().split()))[:6]
                qid = f"{prefix}-{gid}-{q.group(1)}"
                content = f"{title} — {group}\nQ{q.group(1)}: {q.group(2)}"
                risk = _risk(q.group(2))
                chunks.append(KBChunk(content, _base_meta(
                    no, title, question_id=qid, audience=audience, subsection=group,
                    topic=_topic(q.group(2)), treatment_stage=_stage(q.group(2) + " " + (group or "")),
                    risk_level=risk,
                    escalation_route="clinic_urgent_line" if risk in ("urgent", "emergency") else None,
                    citation_label=f"IVF KB §{no} {group} Q{q.group(1)}",
                )))
        elif no == 4:
            for i in range(0, len(lines) - 1, 2):
                head, body = lines[i], lines[i + 1]
                chunks.append(KBChunk(f"{title} — {head}\n{body}", _base_meta(
                    no, title, subsection=head, topic=_topic(head + " " + body),
                    treatment_stage=_stage(head), citation_label=f"IVF KB §4 {head}",
                )))
        elif no == 7:
            for i in range(0, len(lines) - 2, 3):
                head, resp, rule = lines[i], lines[i + 1], lines[i + 2]
                risk = "emergency" if "urgent" in rule.lower() or "immediate" in rule.lower() else (
                    "urgent" if "medication" in rule.lower() or "dose" in rule.lower() else "routine")
                chunks.append(KBChunk(f"Answer pattern — {head}\n{resp}\n{rule}", _base_meta(
                    no, title, subsection=head, topic=_topic(head + " " + resp), risk_level=risk,
                    audience="partner" if "partner" in head.lower() else "both",
                    escalation_route=rule.replace("Routing rule: ", ""), citation_label=f"IVF KB §7 {head}",
                )))
        elif no == 9:
            block, head = [], None
            for line in lines + ["__END__"]:
                if ":" not in line or line == "__END__":
                    if head and block:
                        chunks.append(KBChunk(f"Demo dialogue (synthetic) — {head}\n" + "\n".join(block), _base_meta(
                            no, title, subsection=head, topic=_topic(" ".join(block)), citation_label=f"IVF KB §9 {head}",
                        )))
                    head, block = line, []
                else:
                    block.append(line)
        else:
            body = "\n".join(lines)
            chunks.append(KBChunk(f"{no}. {title}\n{body}", _base_meta(
                no, title, topic="clinic_communication" if no in (8, 10) else "ivf_fundamentals",
                risk_level="emergency" if no == 10 else "education",
            )))
    return chunks


def _try_embed(texts: List[str]) -> Optional[List[List[float]]]:
    if not texts:
        return []
    from app.config import settings
    from app.services.care.health import classify, key_state

    if key_state(settings.openai_api_key, "sk-") != "present":
        return None  # no usable key configured: keyword retrieval, no wasted call
    try:
        from app.services.rag_service import _embed

        return _embed(texts)
    except Exception as exc:  # noqa: BLE001 — keyword retrieval still works
        # provider messages can echo key fragments, so log the type and kind only
        logger.warning("fertility knowledge: embedding unavailable (%s, %s); keyword retrieval only",
                       type(exc).__name__, classify(exc))
        return None


def ingest_kb(db: DBSession, text: Optional[str] = None, *, embed: bool = True) -> Dict[str, Any]:
    """Idempotently (re)index the KB. Returns counts."""
    text = text if text is not None else KB_PATH.read_text(encoding="utf-8")
    digest = kb_digest(text)
    doc = db.query(FertilityKnowledgeDocument).filter_by(document_key=KB_DOCUMENT_KEY).first()
    if doc is None:
        doc = FertilityKnowledgeDocument(
            id=uuid.uuid4(), document_key=KB_DOCUMENT_KEY, title=KB_TITLE, source_type="general_education",
            approval_status="demo_unreviewed", clinic_id=DEMO_CLINIC, version="1.0",
            original_reference="knowledge/ivf_doctor_twin_kb.md",
        )
        db.add(doc)
        db.flush()
    db.query(FertilityKnowledgeChunk).filter_by(document_id=doc.id).delete()
    doc.content_sha256 = digest
    chunks = parse_kb(text)
    vectors = _try_embed([c.content for c in chunks]) if embed else None
    for i, c in enumerate(chunks):
        db.add(FertilityKnowledgeChunk(
            id=uuid.uuid4(), document_id=doc.id, content=c.content, meta=c.meta,
            embedding=vectors[i] if vectors else None,
        ))
    db.commit()
    return {"document_id": str(doc.id), "chunks": len(chunks), "embedded": bool(vectors)}


def ingest_text_document(
    db: DBSession, *, title: str, text: str, source_type: str = "general_education",
    approval_status: str = "demo_unreviewed", clinic_id: Optional[str] = None, audience: str = "both",
    topic: Optional[str] = None, version: str = "1", reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Admin upload of an additional fertility resource (plain text / markdown)."""
    from app.services.rag_service import _chunk_text

    key = f"upload-{uuid.uuid4().hex[:12]}"
    doc = FertilityKnowledgeDocument(
        id=uuid.uuid4(), document_key=key, title=title, source_type=source_type, approval_status=approval_status,
        clinic_id=clinic_id, version=version, original_reference=reference,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    db.add(doc)
    db.flush()
    parts = _chunk_text(text)
    vectors = _try_embed(parts)
    for i, part in enumerate(parts):
        meta = _base_meta(0, title, document_id=key, document_title=title, section=title, source_type=source_type,
                          approval_status=approval_status, clinic_id=clinic_id, audience=audience,
                          topic=topic or _topic(part), treatment_stage=_stage(part), risk_level=_risk(part),
                          version=version, citation_label=f"{title} (part {i + 1})")
        db.add(FertilityKnowledgeChunk(id=uuid.uuid4(), document_id=doc.id, content=part, meta=meta,
                                       embedding=vectors[i] if vectors else None))
    db.commit()
    return {"document_id": str(doc.id), "chunks": len(parts), "embedded": bool(vectors)}


# ── Video transcripts ────────────────────────────────────────────────────

_TS = r"(\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_CUE = re.compile(rf"^\s*({_TS})\s*-->\s*({_TS})")
_BRACKET = re.compile(r"^\s*\[(\d{1,2}(?::\d{2}){1,2})\]\s*(.*)$")


def _seconds(ts: str) -> int:
    ts = ts.replace(",", ".").split(".")[0]
    parts = [int(p) for p in ts.split(":")]
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def parse_transcript(text: str) -> List[Dict[str, Any]]:
    """Parse WebVTT/SRT cues or "[mm:ss] text" lines into segments; plain text is one segment at 0s."""
    segments: List[Dict[str, Any]] = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        cue = _CUE.match(lines[i])
        if cue:
            start, end = _seconds(cue.group(1)), _seconds(cue.group(3))
            i += 1
            body = []
            while i < len(lines) and lines[i].strip():
                body.append(lines[i].strip())
                i += 1
            if body:
                segments.append({"start": start, "end": end, "text": " ".join(body)})
            continue
        br = _BRACKET.match(lines[i])
        if br and br.group(2).strip():
            segments.append({"start": _seconds(br.group(1)), "end": None, "text": br.group(2).strip()})
        i += 1
    if not segments and (text or "").strip():
        return [{"start": 0, "end": None, "text": re.sub(r"\s+", " ", text).strip()}]
    for a, b in zip(segments, segments[1:]):
        if a["end"] is None:
            a["end"] = b["start"]
    return segments


def window_segments(segments: List[Dict[str, Any]], max_seconds: int = 45, max_chars: int = 900) -> List[Dict[str, Any]]:
    """Merge consecutive cues into retrieval windows that keep their start time."""
    out: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for s in segments:
        if cur and (s["start"] - cur["start"] < max_seconds) and len(cur["text"]) + len(s["text"]) < max_chars:
            cur["text"] += " " + s["text"]
            cur["end"] = s["end"]
        else:
            cur = dict(s)
            out.append(cur)
    return out


def index_video_transcript(db: DBSession, video: InstructionalVideo) -> int:
    key = f"video-{video.id}"
    doc = db.query(FertilityKnowledgeDocument).filter_by(document_key=key).first()
    if doc is None:
        doc = FertilityKnowledgeDocument(id=uuid.uuid4(), document_key=key, title=video.title,
                                         source_type="video_transcript", approval_status=video.approval_status,
                                         clinic_id=video.clinic_id, version=video.version)
        db.add(doc)
        db.flush()
    else:
        doc.approval_status = video.approval_status
    db.query(FertilityKnowledgeChunk).filter_by(document_id=doc.id).delete()
    windows = window_segments(parse_transcript(video.transcript or ""))
    vectors = _try_embed([w["text"] for w in windows])
    for i, w in enumerate(windows):
        meta = _base_meta(0, video.title, document_id=key, document_title=video.title, section=f"Video: {video.title}",
                          source_type="video_transcript", approval_status=video.approval_status,
                          clinic_id=video.clinic_id, audience=video.audience or "both",
                          topic=video.topic or _topic(w["text"]), treatment_stage=video.treatment_stage,
                          risk_level="education", version=video.version,
                          medication_name=video.medication_name, device_name=video.device_name,
                          citation_label=f"Video: {video.title} @ {w['start'] // 60}:{w['start'] % 60:02d}")
        db.add(FertilityKnowledgeChunk(id=uuid.uuid4(), document_id=doc.id, video_id=video.id,
                                       start_seconds=w["start"], end_seconds=w.get("end"), content=w["text"],
                                       meta=meta, embedding=vectors[i] if vectors else None))
    db.commit()
    return len(windows)


# ── Retrieval ────────────────────────────────────────────────────────────


def _permitted(meta: Dict[str, Any], role: str, statuses: set, mode: str) -> bool:
    if meta.get("approval_status") not in statuses:
        return False
    aud = meta.get("audience") or "both"
    if aud not in ("both", role):
        return False
    # Patient-specific sources never come through general retrieval.
    if meta.get("consent_scope", "public") != "public" or meta.get("patient_id_if_applicable"):
        return False
    channels = meta.get("permitted_channels")
    if channels and mode not in channels and not (mode == "voice" and "avatar" in channels):
        return False
    expires = meta.get("expires_at")
    if expires and str(expires) < datetime.utcnow().date().isoformat():
        return False
    return True


def _terms(query: str) -> List[str]:
    from app.services.rag_service import _query_terms

    return _query_terms(query)


def retrieve(
    db: DBSession, query: str, *, role: str = "patient", mode: str = "text", top_k: int = 5,
    phase: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if not query or not query.strip():
        return []
    statuses = allowed_approval_statuses(phase)
    pool: Dict[Any, tuple] = {}

    vec = _try_embed([query])
    if vec:
        dist = FertilityKnowledgeChunk.embedding.cosine_distance(vec[0])
        rows = (db.query(FertilityKnowledgeChunk, dist.label("d"))
                .filter(FertilityKnowledgeChunk.embedding.isnot(None)).order_by(dist).limit(top_k * 6).all())
        for row, d in rows:
            pool[row.id] = (row, 1.0 - float(d))

    terms = _terms(query)
    if terms:
        from sqlalchemy import or_

        rows = (db.query(FertilityKnowledgeChunk)
                .filter(or_(*[FertilityKnowledgeChunk.content.ilike(f"%{t}%") for t in terms]))
                .limit(200).all())
        for row in rows:
            frac = sum(1 for t in terms if t in row.content.lower()) / len(terms)
            score = 0.25 + 0.5 * frac  # keyword score on a comparable scale
            if row.id not in pool or pool[row.id][1] < score:
                pool[row.id] = (row, max(score, pool.get(row.id, (None, 0))[1]))

    ranked = sorted(pool.values(), key=lambda x: x[1], reverse=True)
    out = []
    for row, score in ranked:
        meta = row.meta or {}
        if not _permitted(meta, role, statuses, mode):
            continue
        if score < 0.3:
            continue
        out.append({
            "chunk_id": str(row.id), "content": row.content, "score": round(score, 4), "meta": meta,
            "video_id": str(row.video_id) if row.video_id else None, "start_seconds": row.start_seconds,
        })
        if len(out) >= top_k:
            break
    return out


def source_citation(chunk: Dict[str, Any], n: int) -> Dict[str, Any]:
    m = chunk.get("meta") or {}
    return {
        "n": n,
        "label": m.get("citation_label") or m.get("section"),
        "document_title": m.get("document_title"),
        "section": m.get("section"),
        "question_id": m.get("question_id"),
        "source_type": m.get("source_type"),
        "approval_status": m.get("approval_status"),
        "risk_level": m.get("risk_level"),
        "version": m.get("version"),
        "video_id": chunk.get("video_id"),
        "start_seconds": chunk.get("start_seconds"),
    }


def select_videos(db: DBSession, chunks: Iterable[Dict[str, Any]], conversation_text: str) -> List[Dict[str, Any]]:
    """
    Suggest an instructional video only when a retrieved transcript segment
    matched AND, if the video is for a specific medication or device, that
    medication/device was actually named in the conversation. Semantic
    similarity alone never picks a device-specific video.
    """
    text = (conversation_text or "").lower()
    seen, out = set(), []
    for c in chunks:
        vid = c.get("video_id")
        if not vid or vid in seen:
            continue
        video = db.query(InstructionalVideo).filter(InstructionalVideo.id == uuid.UUID(vid)).first()
        if not video:
            continue
        specific = [n for n in (video.medication_name, video.device_name) if n]
        if specific and not all(n.lower() in text for n in specific):
            continue
        seen.add(vid)
        out.append({
            "id": vid, "title": video.title, "start_seconds": c.get("start_seconds") or 0,
            "medication_name": video.medication_name, "device_name": video.device_name,
            "approval_status": video.approval_status,
            "note": "General instructional video — follow your clinic's own instructions for your medication.",
        })
    return out[:2]
