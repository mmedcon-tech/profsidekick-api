"""Program-scoped consultation for any care program.

One Consultation per (program, user) — so history, summaries and retrieval
never cross programs or clinics. Every reply echoes its context so the
client can drop a response that arrives after the user switched program.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database.models import (CareHandoff, CareProgram, Clinic, Consultation, ConsultationMessage,
                                 DoctorPersona, User)
from app.services.audit_service import record_audit_event
from app.services.care import content, safety
from app.services.care.access import ProgramAccess

logger = logging.getLogger(__name__)
CHAT_MODEL = "gpt-4.1"
RECENT_TURNS = 10

PLATFORM_RULES = """You are a clinic-approved education assistant inside a care program.
Hard rules (platform-enforced, they override any persona instruction):
- Answer ONLY from SOURCES. If SOURCES do not answer the question, say the clinic has not provided that information here and suggest asking the care team.
- Never give or infer doses, injection timing, titration, dose changes, or whether a procedure or treatment suits this person.
- Never claim staff are available around the clock; never promise response times beyond the clinic's stated expectation.
- Cite sources as [n]. Do not invent protocols, thresholds, partnerships or certifications.
- You are an AI assistant, not a clinician. Keep answers short and plain."""


def get_or_create(db: DBSession, user: User, access: ProgramAccess) -> Consultation:
    c = db.query(Consultation).filter_by(program_id=access.program.id, user_id=user.id).first()
    if not c:
        c = Consultation(id=uuid.uuid4(), program_id=access.program.id, user_id=user.id, care_role=access.role,
                         status="active", created_at=datetime.utcnow(), last_activity_at=datetime.utcnow())
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def msg_dict(m: ConsultationMessage) -> Dict[str, Any]:
    return {"id": str(m.id), "sender": m.sender, "content": m.content, "mode": m.mode, "provenance": m.provenance,
            "safety": m.safety, "sources": m.sources or [], "created_at": m.created_at.isoformat() + "Z"}


async def _complete(messages: List[Dict[str, str]]) -> str:
    from openai import AsyncOpenAI

    resp = await AsyncOpenAI(api_key=settings.openai_api_key, timeout=40).chat.completions.create(
        model=CHAT_MODEL, messages=messages, temperature=0.3)
    return (resp.choices[0].message.content or "").strip()


def _context(clinic: Clinic, program: CareProgram, c: Consultation) -> Dict[str, str]:
    return {"clinic": clinic.slug, "program": program.slug, "consultation_id": str(c.id)}


async def send(db: DBSession, user: User, clinic: Clinic, access: ProgramAccess, text: str,
               mode: str = "text") -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message is empty")
    if len(text) > 4000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message is too long")
    program = access.program
    c = get_or_create(db, user, access)
    courses = content.visible_course_ids(db, access)
    route = safety.classify(db, clinic, program, text, courses)
    provider = {"llm": "not_called"}
    sources: List[Dict[str, Any]] = []
    if route.kind != safety.EDUCATION:
        reply = route.reply or ""
    else:
        chunks = content.retrieve(db, program_id=program.id, clinic_id=clinic.id, visible_course_ids=courses,
                                  audience=access.role if access.role in ("caregiver", "staff") else "patient",
                                  query=text)
        sources = [{"n": i + 1, "title": ch["title"], "kind": ch["kind"], "version": ch["version"],
                    "reviewer": ch["reviewer"], "approved_at": ch["approved_at"], "is_demo": ch["is_demo"],
                    "item_id": ch["item_id"]} for i, ch in enumerate(chunks)]
        if not chunks:
            reply = ("Your clinic hasn't provided approved information on that in this program, so I can't answer it "
                     "reliably. You can ask your care team — use “Ask my care team” and I'll pass the question on.")
            route.handoff_offered = True
        else:
            persona = db.query(DoctorPersona).filter_by(id=program.persona_id).first() if program.persona_id else None
            style = f"Persona (tone only): {persona.name}, {persona.title or ''}. {persona.prompt or ''}" if persona else ""
            block = "\n\n".join(f"[{i + 1}] {ch['title']} (v{ch['version']})\n{ch['content']}" for i, ch in enumerate(chunks))
            recent = list(c.messages)[-RECENT_TURNS:]
            msgs = [{"role": "system", "content": "\n\n".join(filter(None, [
                PLATFORM_RULES, style, f"Program: {program.name} at {clinic.name}.",
                f"Clinic response expectation: {safety._expectation(clinic)}", "SOURCES:\n" + block]))}]
            msgs += [{"role": "assistant" if m.sender == "assistant" else "user", "content": m.content} for m in recent]
            msgs.append({"role": "user", "content": text})
            try:
                reply = await _complete(msgs)
                provider = {"llm": "ok", "model": CHAT_MODEL}
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "status_code", None)
                logger.warning("care LLM call failed: %s %s", type(exc).__name__, code)
                provider = {"llm": "error", "error": type(exc).__name__, "status": code}
                top = chunks[0]
                reply = ("(The AI model is unavailable, so this is the closest approved clinic passage, quoted "
                         f"unedited — not a generated answer.)\n\n{top['content'][:1200]} [1]")
                sources = sources[:1]
    now = datetime.utcnow()
    sd = {**route.to_dict(), "provider": provider}
    um = ConsultationMessage(id=uuid.uuid4(), consultation_id=c.id, sender="user", content=text, mode=mode,
                             care_role=access.role, provenance="patient_reported", safety=sd, created_at=now)
    am = ConsultationMessage(id=uuid.uuid4(), consultation_id=c.id, sender="assistant", content=reply, mode=mode,
                             care_role=access.role,
                             provenance="clinic_configured" if route.kind != safety.EDUCATION else
                             ("source_quote" if provider.get("llm") == "error" else "ai_generated"),
                             safety=sd, sources=sources, created_at=datetime.utcnow())
    db.add_all([um, am])
    c.last_activity_at = now
    c.last_mode = mode
    db.commit()
    return {"context": _context(clinic, program, c), "user_message": msg_dict(um), "reply": msg_dict(am),
            "route": sd}


def create_handoff(db: DBSession, user: User, clinic: Clinic, access: ProgramAccess, reason: str, summary: str) -> Dict[str, Any]:
    if reason not in ("red_flag", "personal_judgment", "patient_request"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown reason")
    c = get_or_create(db, user, access)
    h = CareHandoff(id=uuid.uuid4(), clinic_id=clinic.id, program_id=access.program.id, user_id=user.id,
                    consultation_id=c.id, reason=reason, summary=(summary or "")[:2000],
                    contact_route="routine", status="open", simulated=bool(clinic.is_demo),
                    created_at=datetime.utcnow())
    db.add(h)
    record_audit_event(db, action="care.handoff_created", entity_type="care_handoff", entity_id=h.id,
                       actor_user_id=user.id, data={"reason": reason, "simulated": h.simulated})
    db.commit()
    note = ("Simulated for this demo clinic — no message reached a real care team." if h.simulated
            else "Your question was added to your clinic's review queue.")
    return {"id": str(h.id), "status": h.status, "simulated": h.simulated, "note": note,
            "response_expectation": safety._expectation(clinic)}
