"""
One persistent consultation per user in IVF Care, shared by text, voice and
avatar. Every turn goes through the same pipeline:

  safety.classify → (fixed escalation reply | retrieval + LLM) → persist

The LLM sees: persona + safety rules, role, patient context grouped by
provenance, the rolling AI summary of older turns (labelled unverified), the
last few turns, and numbered SOURCES from backend-filtered retrieval.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database.models import (
    CareProgram,
    CareProgramMembership,
    Consultation,
    ConsultationMessage,
    PatientContextEntry,
    SimulatedEscalation,
)
from app.services.fertility import doctor, knowledge, safety

logger = logging.getLogger(__name__)

CHAT_MODEL = "gpt-4.1"
RECENT_TURNS = 12          # messages sent verbatim
SUMMARIZE_AFTER = 24       # older messages are folded into the summary


def get_program(db: DBSession, slug: str = doctor.PROGRAM_SLUG) -> CareProgram:
    program = db.query(CareProgram).filter(CareProgram.slug == slug).first()
    if program is None:
        if slug != doctor.PROGRAM_SLUG:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Program not found")
        program = CareProgram(id=uuid.uuid4(), slug=slug, name="IVF Care", is_public=True, clinic_id="demo-harbor",
                              description="Understand IVF, egg freezing, hormonal stimulation, injections, procedures and recovery with your AI Fertility Doctor.")
        db.add(program)
        db.commit()
    return program


def get_membership(db: DBSession, user_id, program: CareProgram) -> Optional[CareProgramMembership]:
    return db.query(CareProgramMembership).filter_by(program_id=program.id, user_id=user_id).first()


def join(db: DBSession, user_id, care_role: str, treatment_stage: Optional[str] = None) -> CareProgramMembership:
    if care_role not in doctor.CARE_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "care_role must be 'patient' or 'partner'")
    if treatment_stage and treatment_stage not in doctor.TREATMENT_STAGES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown treatment stage")
    program = get_program(db)
    m = get_membership(db, user_id, program)
    if m is None:
        m = CareProgramMembership(id=uuid.uuid4(), program_id=program.id, user_id=user_id, care_role=care_role,
                                  treatment_stage=treatment_stage, authorized_scopes=[])
        db.add(m)
    else:
        m.care_role = care_role
        if treatment_stage is not None:
            m.treatment_stage = treatment_stage
        m.updated_at = datetime.utcnow()
    if program.clinic_ref_id:
        # Mirror into the care platform's explicit entitlement (legacy program is open-join).
        from app.database.models import CareEntitlement

        ent = (db.query(CareEntitlement).filter_by(user_id=user_id, program_id=program.id, course_id=None)
               .filter(CareEntitlement.revoked_at.is_(None)).first())
        if ent is None:
            db.add(CareEntitlement(id=uuid.uuid4(), user_id=user_id, clinic_id=program.clinic_ref_id,
                                   program_id=program.id, care_role=care_role, source="open_enrollment",
                                   created_at=datetime.utcnow()))
        else:
            ent.care_role = care_role
    c = db.query(Consultation).filter_by(program_id=program.id, user_id=user_id).first()
    if c is not None:
        c.care_role = care_role
    db.commit()
    db.refresh(m)
    return m


def get_or_create_consultation(db: DBSession, user_id) -> Consultation:
    program = get_program(db)
    m = get_membership(db, user_id, program)
    if m is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Join IVF Care and choose your role first.")
    c = db.query(Consultation).filter_by(program_id=program.id, user_id=user_id).first()
    if c is None:
        c = Consultation(id=uuid.uuid4(), program_id=program.id, user_id=user_id, care_role=m.care_role,
                         status="active", last_activity_at=datetime.utcnow())
        db.add(c)
        db.flush()
        db.add(ConsultationMessage(id=uuid.uuid4(), consultation_id=c.id, sender="assistant",
                                   content=doctor.OPENING_MESSAGE, mode="text", care_role=m.care_role,
                                   provenance="ai_generated", safety={"category": "disclosure"}))
        db.commit()
        db.refresh(c)
    return c


def own_consultation(db: DBSession, user_id, consultation_id) -> Consultation:
    c = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if c is None or str(c.user_id) != str(user_id):
        # Same response for missing and foreign threads.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Consultation not found")
    return c


def message_dict(m: ConsultationMessage) -> Dict[str, Any]:
    return {
        "id": str(m.id), "sender": m.sender, "content": m.content, "mode": m.mode, "care_role": m.care_role,
        "provenance": m.provenance, "safety": m.safety, "sources": m.sources or [], "videos": m.videos or [],
        "created_at": m.created_at.isoformat() + "Z" if m.created_at else None,
    }


def consultation_dict(c: Consultation, *, include_messages: bool = True) -> Dict[str, Any]:
    msgs = list(c.messages or [])
    last = msgs[-1] if msgs else None
    d = {
        "id": str(c.id), "care_role": c.care_role, "status": c.status, "last_mode": c.last_mode,
        "created_at": c.created_at.isoformat() + "Z" if c.created_at else None,
        "last_activity_at": c.last_activity_at.isoformat() + "Z" if c.last_activity_at else None,
        "message_count": len(msgs),
        "last_message": message_dict(last) if last else None,
        "has_summary": bool(c.summary),
    }
    if include_messages:
        d["messages"] = [message_dict(m) for m in msgs]
    return d


def patient_context_block(db: DBSession, user_id, membership: CareProgramMembership) -> str:
    """Context for the prompt, grouped by provenance. Partners see none of a patient's records."""
    if membership.care_role != "patient":
        return "PATIENT CONTEXT: none available to this partner (no authorization granted)."
    rows = (db.query(PatientContextEntry).filter_by(patient_id=user_id)
            .order_by(PatientContextEntry.created_at.desc()).limit(20).all())
    groups = {"verified_clinical": [], "patient_reported": [], "ai_generated": []}
    for r in rows:
        tag = " (SYNTHETIC DEMO)" if r.is_synthetic else ""
        groups.setdefault(r.provenance, []).append(f"- [{r.kind}]{tag} {r.content}")
    if membership.treatment_stage:
        groups["patient_reported"].append(f"- [treatment_stage] {membership.treatment_stage} (selected in app)")
    parts = ["PATIENT CONTEXT (never promote one provenance to another):"]
    parts.append("VERIFIED CLINICAL (from clinic):\n" + ("\n".join(groups["verified_clinical"]) or "- none on file. Do not claim chart access."))
    parts.append("PATIENT-REPORTED (unverified):\n" + ("\n".join(groups["patient_reported"]) or "- none"))
    if groups["ai_generated"]:
        parts.append("AI-GENERATED (unverified summaries):\n" + "\n".join(groups["ai_generated"]))
    return "\n".join(parts)


def _llm_client():
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=settings.openai_api_key)


async def _complete(messages: List[Dict[str, str]], temperature: float = 0.4) -> str:
    resp = await _llm_client().chat.completions.create(model=CHAT_MODEL, messages=messages, temperature=temperature)
    return (resp.choices[0].message.content or "").strip()


def _source_only_reply(chunks: List[Dict[str, Any]]) -> Optional[str]:
    """When the language model is unreachable, answer by quoting the best
    retrieved source instead of failing. Clearly labelled; no generated text."""
    # Bare question-bank entries (meta.question_id) carry no answer; skip them.
    answers = [ch for ch in chunks if not (ch.get("meta") or {}).get("question_id")]
    if not answers:
        return None
    top = answers[0]
    body = top["content"].split("\n", 1)[-1].strip()
    return ("(The AI model is unavailable right now, so here is the closest passage from the knowledge base, unedited.) "
            f"{body[:1200]} [1]\n\nFor anything about your own treatment, please check with your fertility team.")


async def _refresh_summary(db: DBSession, c: Consultation) -> None:
    msgs = list(c.messages)
    if len(msgs) <= SUMMARIZE_AFTER:
        return
    older = msgs[:-RECENT_TURNS]
    if c.summarized_until and older and older[-1].created_at <= c.summarized_until:
        return
    transcript = "\n".join(f"{m.sender}: {m.content}" for m in older[-40:])
    try:
        c.summary = await _complete([
            {"role": "system", "content": "Summarise this fertility consultation for continuity in <=120 words: topics, the user's concerns and anything the user reported. Mark everything as unverified. No advice."},
            {"role": "user", "content": (("Previous summary: " + c.summary + "\n") if c.summary else "") + transcript},
        ], temperature=0.2)
        c.summarized_until = older[-1].created_at
    except Exception as exc:  # noqa: BLE001
        logger.warning("consultation summary failed: %s", exc)


def _conversation_text(c: Consultation, user_text: str) -> str:
    recent_user = [m.content for m in list(c.messages)[-8:] if m.sender == "user"]
    return " ".join(recent_user + [user_text])


async def send(db: DBSession, user_id, consultation_id, text: str, mode: str = "text") -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message is empty")
    if len(text) > 4000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message is too long")
    mode = mode if mode in doctor.MODES else "text"
    c = own_consultation(db, user_id, consultation_id)
    program = db.query(CareProgram).filter_by(id=c.program_id).first()
    membership = get_membership(db, user_id, program)
    role = membership.care_role if membership else c.care_role

    verdict = safety.classify(text, role)
    convo_text = _conversation_text(c, text)
    phase = knowledge.knowledge_phase()
    chunks = knowledge.retrieve(db, convo_text if len(text) < 40 else text, role=role, mode=mode, phase=phase)
    sources = [knowledge.source_citation(ch, i + 1) for i, ch in enumerate(chunks)]
    videos = knowledge.select_videos(db, chunks, convo_text)

    if verdict.deterministic:
        reply = verdict.fixed_response or ""
        sources = [s for s in sources if s.get("risk_level") in ("urgent", "emergency")][:2] or sources[:1]
        videos = []  # never show a how-to video in response to an error/emergency
    elif phase == 2 and not chunks:
        reply = ("I don't have an approved clinic source that answers this, so I can't give you a reliable answer. "
                 "Please ask your fertility team — I can help you write the question down.")
    else:
        recent = list(c.messages)[-RECENT_TURNS:]
        source_block = "\n\n".join(f"[{i + 1}] ({ch['meta'].get('citation_label')}; {ch['meta'].get('source_type')}; "
                                   f"{ch['meta'].get('approval_status')})\n{ch['content']}" for i, ch in enumerate(chunks))
        guard = {
            safety.PATIENT_DECISION: "This is a patient-specific medical decision: explain the general considerations and refer the decision to the treating clinician. No personal predictions.",
            safety.CLINIC: "This needs clinic-specific instructions: use an approved clinic source if one is in SOURCES; otherwise say the clinic's own instructions are not available here and suggest asking the clinic.",
            safety.GENERAL: "General education question.",
        }[verdict.category]
        phase_rule = ("PHASE 2: answer ONLY from SOURCES. If they don't answer it, say so." if phase == 2 else
                      "PHASE 1 DEMO: you may use general medical knowledge for general education, but SOURCES take priority and you must not invent patient-specific facts.")
        system = "\n\n".join(filter(None, [
            doctor.SYSTEM_PROMPT, doctor.ROLE_STYLE.get(role, ""), doctor.MODE_STYLE[mode],
            f"SAFETY CLASSIFICATION: {verdict.category}. {guard}", phase_rule,
            patient_context_block(db, user_id, membership) if membership else None,
            ("EARLIER CONVERSATION SUMMARY (AI-generated, unverified):\n" + c.summary) if c.summary else None,
            "SOURCES:\n" + (source_block or "(no matching sources found — say when you are answering from general knowledge)"),
        ]))
        messages = [{"role": "system", "content": system}]
        messages += [{"role": "assistant" if m.sender == "assistant" else "user", "content": m.content} for m in recent]
        messages.append({"role": "user", "content": text})
        try:
            reply = await _complete(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fertility LLM call failed (%s); using source-only fallback", type(exc).__name__)
            reply = _source_only_reply(chunks)
            if reply is None:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI service is unavailable. Please try again.")

    now = datetime.utcnow()
    user_msg = ConsultationMessage(id=uuid.uuid4(), consultation_id=c.id, sender="user", content=text, mode=mode,
                                   care_role=role, provenance="patient_reported", safety=verdict.to_dict(),
                                   created_at=now)
    ai_msg = ConsultationMessage(id=uuid.uuid4(), consultation_id=c.id, sender="assistant", content=reply, mode=mode,
                                 care_role=role, provenance="ai_generated", safety=verdict.to_dict(),
                                 sources=sources, videos=videos, created_at=datetime.utcnow())
    db.add_all([user_msg, ai_msg])
    c.last_activity_at = now
    c.last_mode = mode
    c.care_role = role
    db.commit()
    db.refresh(c)
    await _refresh_summary(db, c)
    db.commit()
    return {"user_message": message_dict(user_msg), "reply": message_dict(ai_msg), "safety": verdict.to_dict(),
            "consultation_id": str(c.id)}


def simulate_escalation(db: DBSession, user_id, consultation_id, category: str, summary: str) -> Dict[str, Any]:
    c = own_consultation(db, user_id, consultation_id)
    e = SimulatedEscalation(id=uuid.uuid4(), consultation_id=c.id, category=category[:40] or "unspecified",
                            summary=(summary or "")[:2000] or "Patient requested contact with the care team.",
                            simulated=True)
    db.add(e)
    db.add(ConsultationMessage(id=uuid.uuid4(), consultation_id=c.id, sender="assistant", mode="text",
                               care_role=c.care_role, provenance="ai_generated",
                               content=("Simulated: request placed in the demo nurse queue. No real message was sent — "
                                        "please contact your clinic directly using its urgent line."),
                               safety={"category": "simulated_escalation", "simulated": True}))
    c.last_activity_at = datetime.utcnow()
    db.commit()
    return {"id": str(e.id), "simulated": True, "label": safety.SIMULATED_LABEL, "category": e.category}


def clear_history(db: DBSession, user_id, consultation_id) -> None:
    c = own_consultation(db, user_id, consultation_id)
    db.query(ConsultationMessage).filter_by(consultation_id=c.id).delete()
    db.query(SimulatedEscalation).filter_by(consultation_id=c.id).delete()
    c.summary = None
    c.summarized_until = None
    db.add(ConsultationMessage(id=uuid.uuid4(), consultation_id=c.id, sender="assistant", content=doctor.OPENING_MESSAGE,
                               mode="text", care_role=c.care_role, provenance="ai_generated",
                               safety={"category": "disclosure"}))
    c.last_activity_at = datetime.utcnow()
    db.commit()
