"""
Publisher Learning System — service layer.

Handles:
  - Chat conversations (create / continue / retrieve)
  - Feedback preference recording
  - Per-publisher key-value preferences

AI backend: OpenAI Chat Completions (model-agnostic prompt assembly).
The prompt builder pulls context from:
  AvatarTemplate.hidden_system_prompt   — avatar's core behaviour
  AvatarConfiguration.rubrics           — grading criteria
  AvatarConfiguration.knowledge_documents.content_text — reference material
  publisher_preferences                 — publisher-level overrides

To switch to a different LLM, replace _call_llm() only.
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any, List, Optional
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status
from openai import AsyncOpenAI

from app.config import settings
from app.database.models import (
    AvatarTemplate,
    AvatarTemplateVersion,
    PublisherConversation,
    PublisherMessage,
    PublisherMessageFeedback,
    FeedbackPreference,
    PublisherPreference,
    PublisherResponseEdit,
    Avatar,
    AvatarConfiguration,
    Session as SessionModel,
)
from app.services.context_builder import build_chat_system_prompt
from app.services.summarization_service import get_recent_session_summary, get_user_memories

_openai = AsyncOpenAI(api_key=settings.openai_api_key)

# Maximum conversation turns sent as context to the LLM before summarizing
_MAX_CONTEXT_MESSAGES = 20
# When history exceeds this, oldest messages are summarized
_SUMMARIZE_THRESHOLD = 15


# ─── Prompt assembly ────────────────────────────────────────────────────────

def _resolve_conversation_prompt(avatar: Optional[Avatar]) -> Optional[str]:
    """
    Resolve the (legacy) conversation_prompt from the avatar's template.
    Priority: frozen version → current published version → legacy column.
    """
    if not avatar or not avatar.template:
        return None
    template: AvatarTemplate = avatar.template
    version = avatar.template_version or template.current_version
    if version:
        prompt = (version.conversation_prompt or "").strip()
        if prompt:
            return prompt
    return (template.hidden_system_prompt or "").strip() or None


def _resolve_mode_prompts(avatar: Optional[Avatar]) -> dict:
    """
    Resolve all mode-specific prompt fields from the avatar's template version.
    Returns a dict with: conversation_prompt, teaching_prompt, examination_prompt.
    """
    result = {"conversation_prompt": None, "teaching_prompt": None, "examination_prompt": None}
    if not avatar or not avatar.template:
        return result
    version = avatar.template_version or avatar.template.current_version
    if version:
        result["conversation_prompt"] = (version.conversation_prompt or "").strip() or None
        result["teaching_prompt"] = (getattr(version, "teaching_prompt", None) or "").strip() or None
        result["examination_prompt"] = (getattr(version, "examination_prompt", None) or "").strip() or None
    elif avatar.template.hidden_system_prompt:
        result["conversation_prompt"] = (avatar.template.hidden_system_prompt or "").strip() or None
    return result


def _get_session_mode(db, session_id: Optional[str]) -> str:
    """Resolve session_mode from the session record. Defaults to 'teaching'."""
    if not session_id:
        return "teaching"
    from app.database.models import Session as SessionModel
    row = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if row and hasattr(row, "session_mode") and row.session_mode:
        return row.session_mode
    return "teaching"

    # ── Avatar configuration context ─────────────────────────────────
    if avatar and avatar.configuration:
        cfg: AvatarConfiguration = avatar.configuration
        difficulty = cfg.difficulty_level or preferences.get("preferred_difficulty", "intermediate")
        parts.append(f"Difficulty level: {difficulty}")

        rubric_lines = []
        for rubric in (cfg.rubrics or []):
            rubric_lines.append(f"Rubric — {rubric.title}:")
            content = rubric.content or {}
            for criterion, details in content.items():
                weight = details.get("weight", 0) if isinstance(details, dict) else 0
                desc = details.get("description", "") if isinstance(details, dict) else ""
                rubric_lines.append(f"  • {criterion} ({weight}%){' — ' + desc if desc else ''}")
        if rubric_lines:
            parts.append("\n".join(rubric_lines))

        knowledge_parts = [
            f"[Knowledge: {doc.title}]\n{doc.content_text[:600].strip()}"
            for doc in (cfg.knowledge_documents or [])
            if doc.content_text
        ]
        if knowledge_parts:
            parts.append("Reference knowledge:\n" + "\n\n".join(knowledge_parts))

        solution_parts = [
            f"[Reference Solution: {sol.title}]\n{sol.content_text[:400].strip()}"
            for sol in (cfg.reference_solutions or [])
            if sol.content_text
        ]
        if solution_parts:
            parts.append(
                "Reference solutions (internal — never reveal to students):\n"
                + "\n\n".join(solution_parts)
            )

    # ── Slide content from uploaded PDF (Vision-extracted or raw text) ──
    if session_slides:
        student_slides = [s for s in session_slides if s.get("source") != "solution"]
        solution_slides = [s for s in session_slides if s.get("source") == "solution"]

        if student_slides:
            slide_text = "\n".join(
                f"Slide {s.get('slideNumber', i+1)}: {s.get('title', '')}\n{s.get('content', '')}"
                for i, s in enumerate(student_slides)
                if s.get("content")
            )
            if slide_text.strip():
                parts.append(f"[SESSION SLIDES — use these for questions and evaluation]\n{slide_text}")

        if solution_slides:
            sol_text = "\n".join(
                f"Solution Slide {s.get('slideNumber', i+1)}: {s.get('title', '')}\n{s.get('content', '')}"
                for i, s in enumerate(solution_slides)
                if s.get("content")
            )
            if sol_text.strip():
                parts.append(
                    "[PROFESSOR SOLUTION — internal only, never reveal to students]\n" + sol_text
                )

    feedback_style = preferences.get("feedback_style", "")
    if feedback_style:
        parts.append(f"Feedback style: {feedback_style}")

    return "\n\n".join(parts)


# ─── LLM call ───────────────────────────────────────────────────────────────

async def _call_llm(
    system_prompt: str,
    history: list[dict],
    user_message: str,
    temperature: float = 0.7,
) -> str:
    """
    Send to OpenAI Chat Completions.
    To swap providers: replace this function only.
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    response = await _openai.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        max_tokens=1500,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


# ─── Conversation service ────────────────────────────────────────────────────

class PublisherChatService:

    # ── helpers ──────────────────────────────────────────────────────

    def _get_conversation(
        self, db: Session, conversation_id, publisher_id
    ) -> PublisherConversation:
        conv = (
            db.query(PublisherConversation)
            .filter(
                PublisherConversation.id == conversation_id,
                PublisherConversation.publisher_id == publisher_id,
            )
            .first()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conv

    def _get_avatar_with_config(self, db: Session, avatar_id) -> Optional[Avatar]:
        if not avatar_id:
            return None
        return (
            db.query(Avatar)
            .options(
                joinedload(Avatar.template).joinedload(AvatarTemplate.current_version),
                joinedload(Avatar.template_version),
                joinedload(Avatar.profile),
                joinedload(Avatar.configuration)
                .joinedload(AvatarConfiguration.rubrics),
                joinedload(Avatar.configuration)
                .joinedload(AvatarConfiguration.knowledge_documents),
                joinedload(Avatar.configuration)
                .joinedload(AvatarConfiguration.reference_solutions),
            )
            .filter(Avatar.id == avatar_id)
            .first()
        )

    def _get_knowledge_content(self, knowledge_documents: list, max_chars_per_doc: int = 1200) -> List[str]:
        """
        Return knowledge content as a list of text strings, truncated per document.
        """
        return [
            doc.content_text[:max_chars_per_doc].strip()
            for doc in knowledge_documents
            if doc.content_text and doc.content_text.strip()
        ]

    def _get_session_slides(self, db: Session, session_id: Optional[str]) -> list[dict]:
        """Load Vision-extracted (or raw) slide content from a session's slides_details JSONB."""
        if not session_id:
            return []
        session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id
        ).first()
        if not session or not session.slides_details:
            return []
        return session.slides_details  # list of slide dicts with slideNumber, title, content, source

    def _get_publisher_preferences(self, db: Session, publisher_id) -> dict:
        rows = (
            db.query(PublisherPreference)
            .filter(PublisherPreference.publisher_id == publisher_id)
            .all()
        )
        return {r.key: r.value for r in rows}

    def _get_publisher_feedback_notes(self, db: Session, publisher_id, avatar_id=None, limit: int = 8) -> List[str]:
        """
        Return recent publisher feedback comments for this avatar.
        Used to inject as [Publisher Preferences] context into the system prompt.
        """
        q = (
            db.query(PublisherMessageFeedback)
            .filter(
                PublisherMessageFeedback.publisher_id == publisher_id,
                PublisherMessageFeedback.comment.isnot(None),
                PublisherMessageFeedback.comment != "",
            )
        )
        if avatar_id:
            q = q.filter(PublisherMessageFeedback.avatar_id == avatar_id)
        rows = q.order_by(PublisherMessageFeedback.created_at.desc()).limit(limit).all()
        return [r.comment for r in rows if r.comment]

    def _title_from_message(self, message: str) -> str:
        words = message.strip().split()
        title = " ".join(words[:8])
        return title[:255] if len(title) <= 255 else title[:252] + "..."

    # ── chat ─────────────────────────────────────────────────────────

    async def chat(
        self,
        db: Session,
        publisher_id,
        request,
    ) -> dict:
        """
        Continue or start a conversation.
        1. Resolve or create conversation.
        2. Build system prompt from avatar context + preferences.
        3. Call LLM with last N turns as context.
        4. Persist both turns.
        5. Return reply.
        """
        # Resolve conversation
        if request.conversation_id:
            conv = self._get_conversation(db, request.conversation_id, publisher_id)
        else:
            avatar_id = request.avatar_id
            conv = PublisherConversation(
                id=uuid.uuid4(),
                publisher_id=publisher_id,
                avatar_id=avatar_id,
                title=self._title_from_message(request.message),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(conv)
            db.flush()  # get id without committing

        # Load avatar + preferences
        avatar_id = request.avatar_id or conv.avatar_id
        avatar = self._get_avatar_with_config(db, avatar_id)
        if avatar_id and not avatar:
            raise HTTPException(
                status_code=404,
                detail=f"Avatar '{avatar_id}' not found or has been deleted",
            )
        preferences = self._get_publisher_preferences(db, publisher_id)
        if request.preferences:
            preferences.update(request.preferences)

        # Role from preferences (set by frontend when user selects a role)
        role_info = preferences.get("selected_role") or {}
        role_label = role_info.get("name") if isinstance(role_info, dict) else None
        role_context = role_info.get("prompt_context") if isinstance(role_info, dict) else None

        # Load session context
        session_id = getattr(request, "session_id", None)
        session_slides = self._get_session_slides(db, session_id)
        session_summary = get_recent_session_summary(db, session_id) if session_id else None
        memories = get_user_memories(db, publisher_id, avatar_id=avatar_id)
        session_mode = _get_session_mode(db, session_id)

        # Resolve all mode-specific prompts from AvatarTemplateVersion
        prompts = _resolve_mode_prompts(avatar)

        # Knowledge content (RAG chunks or truncated)
        cfg = avatar.configuration if avatar else None
        knowledge_chunks = self._get_knowledge_content(cfg.knowledge_documents) if cfg else []
        reference_solutions = cfg.reference_solutions if cfg else []
        rubrics = cfg.rubrics if cfg else []
        difficulty = cfg.difficulty_level if cfg else None

        # Publisher feedback notes injected as context
        feedback_notes = self._get_publisher_feedback_notes(db, publisher_id, avatar_id=avatar_id)

        # Build system prompt via centralized context builder
        system_prompt = build_chat_system_prompt(
            avatar_name=avatar.name if avatar else "AI Assistant",
            conversation_prompt=prompts["conversation_prompt"],
            teaching_prompt=prompts["teaching_prompt"],
            examination_prompt=prompts["examination_prompt"],
            refined_prompt=avatar.profile.refined_prompt if avatar and avatar.profile else None,
            session_mode=session_mode,
            role_label=role_label,
            role_context=role_context,
            difficulty_level=difficulty,
            rubrics=rubrics,
            knowledge_chunks=knowledge_chunks,
            reference_solutions=reference_solutions,
            session_slides=session_slides,
            session_summary=session_summary,
            memories=memories,
            preferences=preferences,
            publisher_feedback_notes=feedback_notes,
        )

        # Build conversation history (rolling window with summarization)
        existing_messages = (
            db.query(PublisherMessage)
            .filter(PublisherMessage.conversation_id == conv.id)
            .order_by(PublisherMessage.created_at)
            .all()
        )
        chat_messages = [m for m in existing_messages if m.role in ("user", "assistant")]

        # Rolling summarization: if history is long, inject a summary of earliest messages
        history: list = []
        if len(chat_messages) > _SUMMARIZE_THRESHOLD:
            older = chat_messages[:-_SUMMARIZE_THRESHOLD]
            recent = chat_messages[-_SUMMARIZE_THRESHOLD:]
            # Build a one-shot summary of the older portion (fire-and-forget in background)
            older_text = "\n".join(f"{m.role}: {m.content[:300]}" for m in older[:10])
            history.append({
                "role": "system",
                "content": f"[Earlier conversation summary]\n{older_text}\n[End summary]"
            })
            history.extend({"role": m.role, "content": m.content} for m in recent)
        else:
            history.extend({"role": m.role, "content": m.content} for m in chat_messages)

        turn_number = len([m for m in existing_messages if m.role == "user"]) + 1

        # Call LLM — or use pre-selected content if the publisher already chose one
        if hasattr(request, "selected_content") and request.selected_content:
            reply = request.selected_content
        else:
            reply = await _call_llm(system_prompt, history, request.message)

        # Persist user message
        user_msg = PublisherMessage(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="user",
            content=request.message,
            created_at=datetime.utcnow(),
        )
        db.add(user_msg)

        # Persist assistant reply
        assistant_msg = PublisherMessage(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=reply,
            created_at=datetime.utcnow(),
        )
        db.add(assistant_msg)

        # Update conversation timestamp
        conv.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(conv)
        db.refresh(assistant_msg)

        return {
            "conversation_id": conv.id,
            "message_id": assistant_msg.id,
            "reply": reply,
            "turn_number": turn_number,
            "created_at": assistant_msg.created_at,
        }

    # ── generate multiple options ─────────────────────────────────────

    async def generate_options(self, db: Session, publisher_id, request) -> dict:
        """
        Generate N independent AI responses for the same user message.
        Each call uses a slightly higher temperature to ensure diversity.
        Nothing is persisted — the publisher must call commit_selection()
        to write the chosen option to the conversation.
        """
        # Ensure/create conversation container
        if request.conversation_id:
            conv = self._get_conversation(db, request.conversation_id, publisher_id)
        else:
            conv = PublisherConversation(
                id=uuid.uuid4(),
                publisher_id=publisher_id,
                avatar_id=request.avatar_id,
                title=self._title_from_message(request.message),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)

        avatar_id = request.avatar_id or conv.avatar_id
        avatar = self._get_avatar_with_config(db, avatar_id)
        if avatar_id and not avatar:
            raise HTTPException(
                status_code=404,
                detail=f"Avatar '{avatar_id}' not found or has been deleted",
            )
        preferences = self._get_publisher_preferences(db, publisher_id)
        if request.preferences:
            preferences.update(request.preferences)

        role_info = preferences.get("selected_role") or {}
        role_label = role_info.get("name") if isinstance(role_info, dict) else None
        role_context = role_info.get("prompt_context") if isinstance(role_info, dict) else None

        session_id_opts = getattr(request, "session_id", None)
        session_slides = self._get_session_slides(db, session_id_opts)
        session_mode_opts = _get_session_mode(db, session_id_opts)
        prompts_opts = _resolve_mode_prompts(avatar)
        cfg = avatar.configuration if avatar else None
        knowledge_chunks = self._get_knowledge_content(cfg.knowledge_documents) if cfg else []
        feedback_notes_opts = self._get_publisher_feedback_notes(db, publisher_id, avatar_id=avatar_id)

        system_prompt = build_chat_system_prompt(
            avatar_name=avatar.name if avatar else "AI Assistant",
            conversation_prompt=prompts_opts["conversation_prompt"],
            teaching_prompt=prompts_opts["teaching_prompt"],
            examination_prompt=prompts_opts["examination_prompt"],
            refined_prompt=avatar.profile.refined_prompt if avatar and avatar.profile else None,
            session_mode=session_mode_opts,
            role_label=role_label,
            role_context=role_context,
            difficulty_level=cfg.difficulty_level if cfg else None,
            rubrics=cfg.rubrics if cfg else [],
            knowledge_chunks=knowledge_chunks,
            reference_solutions=cfg.reference_solutions if cfg else [],
            session_slides=session_slides,
            publisher_feedback_notes=feedback_notes_opts,
        )

        existing = (
            db.query(PublisherMessage)
            .filter(PublisherMessage.conversation_id == conv.id)
            .order_by(PublisherMessage.created_at)
            .all()
        )
        history = [
            {"role": m.role, "content": m.content}
            for m in existing[-_MAX_CONTEXT_MESSAGES:]
            if m.role in ("user", "assistant")
        ]

        # Vary temperatures for diverse options
        n = request.n if hasattr(request, "n") else 3
        temps = [0.7 + i * 0.15 for i in range(n)]

        responses = await asyncio.gather(
            *[_call_llm(system_prompt, history, request.message, t) for t in temps],
            return_exceptions=True,
        )

        options = []
        labels = "ABCDEFGHIJ"
        for i, r in enumerate(responses):
            content = r if isinstance(r, str) else f"[Generation failed: {r}]"
            options.append({"option_id": labels[i], "content": content})

        return {"conversation_id": conv.id, "options": options}

    # ── commit a selected option ──────────────────────────────────────

    async def commit_selection(
        self, db: Session, publisher_id, request
    ) -> dict:
        """
        Persist the publisher's chosen option as the assistant turn.
        Also records the rejected alternatives as a FeedbackPreference.
        """
        conv = self._get_conversation(db, request.conversation_id, publisher_id)

        # Persist user message
        user_msg = PublisherMessage(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="user",
            content=request.user_message,
            created_at=datetime.utcnow(),
        )
        db.add(user_msg)

        # Persist selected response as assistant turn
        assistant_msg = PublisherMessage(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=request.selected_response,
            created_at=datetime.utcnow(),
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.utcnow()

        # Record feedback preference
        fb = FeedbackPreference(
            id=uuid.uuid4(),
            publisher_id=publisher_id,
            avatar_id=getattr(request, "avatar_id", None),
            prompt=request.user_message,
            selected_response=request.selected_response,
            rejected_responses=[r for r in (request.rejected_responses or []) if r],
            feedback_notes=getattr(request, "feedback_notes", None),
            created_at=datetime.utcnow(),
        )
        db.add(fb)

        db.commit()
        db.refresh(assistant_msg)
        db.refresh(fb)

        return {
            "conversation_id": conv.id,
            "message_id": assistant_msg.id,
            "feedback_id": fb.id,
            "created_at": assistant_msg.created_at,
        }

    # ── list conversations ────────────────────────────────────────────

    def list_conversations(self, db: Session, publisher_id) -> dict:
        convs = (
            db.query(PublisherConversation)
            .filter(PublisherConversation.publisher_id == publisher_id)
            .order_by(PublisherConversation.updated_at.desc())
            .all()
        )
        summaries = []
        for c in convs:
            msg_count = (
                db.query(PublisherMessage)
                .filter(PublisherMessage.conversation_id == c.id)
                .count()
            )
            summaries.append({
                "id": c.id,
                "avatar_id": c.avatar_id,
                "title": c.title,
                "message_count": msg_count,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            })
        return {"conversations": summaries, "total": len(summaries)}

    # ── get conversation detail ───────────────────────────────────────

    def get_conversation(self, db: Session, publisher_id, conversation_id) -> dict:
        conv = self._get_conversation(db, conversation_id, publisher_id)
        messages = (
            db.query(PublisherMessage)
            .filter(PublisherMessage.conversation_id == conv.id)
            .order_by(PublisherMessage.created_at)
            .all()
        )
        return {
            "id": conv.id,
            "avatar_id": conv.avatar_id,
            "title": conv.title,
            "messages": [
                {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
                for m in messages
            ],
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
        }

    # ── delete conversation ───────────────────────────────────────────

    def delete_conversation(self, db: Session, publisher_id, conversation_id) -> None:
        conv = self._get_conversation(db, conversation_id, publisher_id)
        db.delete(conv)
        db.commit()

    # ── AI-initiated opening (guided session start) ───────────────────

    async def start_conversation(self, db: Session, publisher_id, request) -> dict:
        """
        Create a new conversation and generate the AI's opening message.
        No user turn is sent — the AI speaks first based on the assembled
        system prompt. The opening is stored as an 'assistant' message.
        """
        avatar_id = request.avatar_id
        conv = PublisherConversation(
            id=uuid.uuid4(),
            publisher_id=publisher_id,
            avatar_id=avatar_id,
            title="Session",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(conv)
        db.flush()

        avatar = self._get_avatar_with_config(db, avatar_id)
        preferences = self._get_publisher_preferences(db, publisher_id)
        if request.preferences:
            preferences.update(request.preferences)

        role_info = preferences.get("selected_role") or {}
        role_label = role_info.get("name") if isinstance(role_info, dict) else None
        role_context = role_info.get("prompt_context") if isinstance(role_info, dict) else None

        session_id_start = getattr(request, "session_id", None)
        session_slides = self._get_session_slides(db, session_id_start)
        session_summary = get_recent_session_summary(db, session_id_start) if session_id_start else None
        memories = get_user_memories(db, publisher_id, avatar_id=avatar_id)
        session_mode_start = _get_session_mode(db, session_id_start)
        prompts_start = _resolve_mode_prompts(avatar)
        feedback_notes = self._get_publisher_feedback_notes(db, publisher_id, avatar_id=avatar_id)

        cfg = avatar.configuration if avatar else None
        knowledge_chunks = self._get_knowledge_content(cfg.knowledge_documents) if cfg else []

        system_prompt = build_chat_system_prompt(
            avatar_name=avatar.name if avatar else "AI Assistant",
            conversation_prompt=prompts_start["conversation_prompt"],
            teaching_prompt=prompts_start["teaching_prompt"],
            examination_prompt=prompts_start["examination_prompt"],
            refined_prompt=avatar.profile.refined_prompt if avatar and avatar.profile else None,
            session_mode=session_mode_start,
            role_label=role_label,
            role_context=role_context,
            difficulty_level=cfg.difficulty_level if cfg else None,
            rubrics=cfg.rubrics if cfg else [],
            knowledge_chunks=knowledge_chunks,
            reference_solutions=cfg.reference_solutions if cfg else [],
            session_slides=session_slides,
            session_summary=session_summary,
            memories=memories,
            preferences=preferences,
            publisher_feedback_notes=feedback_notes,
        )

        # Prompt the AI to generate an opening, grounded in the examiner persona
        trigger = (
            "Begin the session. Welcome the student and ask them to provide a high-level overview "
            "of their assignment and walk you through their solution from start to finish. "
            "Do not ask multiple questions at once. Keep it concise and direct."
        )
        opening = await _call_llm(system_prompt, [], trigger, temperature=0.6)

        assistant_msg = PublisherMessage(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            role="assistant",
            content=opening,
            created_at=datetime.utcnow(),
        )
        db.add(assistant_msg)

        # Title the conversation based on role or session context
        role_label_short = role_label or "Session"
        conv.title = role_label_short[:100]
        conv.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(assistant_msg)

        return {
            "conversation_id": conv.id,
            "message_id": assistant_msg.id,
            "opening_message": opening,
            "created_at": assistant_msg.created_at,
        }

    # ── editable AI responses ─────────────────────────────────────────

    def save_response_edit(
        self, db: Session, publisher_id, message_id, data
    ) -> PublisherResponseEdit:
        """
        Save a publisher's inline edit to an AI-generated response.
        Records original and edited text as a 'publisher_refinement' for future analysis.
        """
        msg = (
            db.query(PublisherMessage)
            .filter(PublisherMessage.id == message_id)
            .first()
        )
        if not msg:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Message not found")

        row = PublisherResponseEdit(
            id=uuid.uuid4(),
            message_id=message_id,
            publisher_id=publisher_id,
            avatar_id=data.avatar_id,
            session_id=data.session_id,
            original_content=data.original_content,
            edited_content=data.edited_content,
            edit_type="publisher_refinement",
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    # ── per-message feedback (legacy — retained for data preservation) ─────────

    def record_message_feedback(
        self, db: Session, publisher_id, message_id, data
    ) -> PublisherMessageFeedback:
        """
        Record thumbs-up/down + optional comment for a specific AI message.
        If a feedback row for this publisher+message already exists, update it.
        """
        existing = (
            db.query(PublisherMessageFeedback)
            .filter(
                PublisherMessageFeedback.message_id == message_id,
                PublisherMessageFeedback.publisher_id == publisher_id,
            )
            .first()
        )
        if existing:
            if data.rating is not None:
                existing.rating = data.rating
            if data.comment is not None:
                existing.comment = data.comment
            if data.avatar_id is not None:
                existing.avatar_id = data.avatar_id
            db.commit()
            db.refresh(existing)
            return existing

        row = PublisherMessageFeedback(
            id=uuid.uuid4(),
            message_id=message_id,
            publisher_id=publisher_id,
            avatar_id=data.avatar_id,
            rating=data.rating,
            comment=data.comment,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


# ─── Preference service ──────────────────────────────────────────────────────

class PreferenceService:

    def list(self, db: Session, publisher_id) -> list:
        return (
            db.query(PublisherPreference)
            .filter(PublisherPreference.publisher_id == publisher_id)
            .all()
        )

    def upsert(self, db: Session, publisher_id, key: str, value: Any) -> PublisherPreference:
        row = (
            db.query(PublisherPreference)
            .filter(
                PublisherPreference.publisher_id == publisher_id,
                PublisherPreference.key == key,
            )
            .first()
        )
        if row:
            row.value = value
            row.updated_at = datetime.utcnow()
        else:
            row = PublisherPreference(
                id=uuid.uuid4(),
                publisher_id=publisher_id,
                key=key,
                value=value,
                updated_at=datetime.utcnow(),
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        return row


# ─── Module-level singletons ─────────────────────────────────────────────────
publisher_chat_service = PublisherChatService()
preference_service = PreferenceService()
