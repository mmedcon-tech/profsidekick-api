from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.database.models.prompts import AvatarPromptConfig, PromptTemplate


class PromptResolutionService:
    """
    Single point of truth for resolving the effective prompt text for a given
    avatar + use_case combination at runtime.

    Resolution priority:
      0. prompt_template_id (direct)          — session-specific override (Phase 2)
      1. AvatarPromptConfig.override_body     — publisher has customised the text
      2. AvatarPromptConfig → PromptTemplate  — publisher selected a template as-is
      3. System-default PromptTemplate        — no avatar config; use admin default
      4. None                                 — caller falls back to legacy path
         (AvatarTemplateVersion fields for sessions, autograder_cache for grading)

    Steps 1–2 are skipped when avatar_id is None (standalone/template-only context).
    Step 0 is skipped when prompt_template_id is None.
    """

    def resolve(
        self,
        db: Session,
        avatar_id: Optional[UUID],
        use_case: str,
        prompt_template_id: Optional[UUID] = None,
    ) -> Optional[str]:
        """
        Return the effective prompt body string, or None if no prompt is
        configured for this avatar/use_case (caller applies its own fallback).

        prompt_template_id: when provided (e.g. from Session.prompt_template_id)
        this takes highest priority over all avatar-level configuration.
        """
        # Priority 0: direct session-level template
        if prompt_template_id is not None:
            body = self._resolve_direct_template(db, prompt_template_id)
            if body is not None:
                return body

        if avatar_id is not None:
            body = self._resolve_from_avatar(db, avatar_id, use_case)
            if body is not None:
                return body

        return self._resolve_system_default(db, use_case)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_direct_template(
        self,
        db: Session,
        template_id: UUID,
    ) -> Optional[str]:
        template = (
            db.query(PromptTemplate)
            .filter(
                PromptTemplate.id == template_id,
                PromptTemplate.is_active == True,
            )
            .first()
        )
        return template.body if template else None

    def _resolve_from_avatar(
        self,
        db: Session,
        avatar_id: UUID,
        use_case: str,
    ) -> Optional[str]:
        config = (
            db.query(AvatarPromptConfig)
            .filter(
                AvatarPromptConfig.avatar_id == avatar_id,
                AvatarPromptConfig.use_case == use_case,
                AvatarPromptConfig.is_enabled == True,
            )
            .first()
        )
        if config is None:
            return None

        # Priority 1: publisher-written override text
        if config.override_body:
            return config.override_body

        # Priority 2: admin template body (publisher selected but did not edit)
        if config.prompt_template_id is not None:
            template = (
                db.query(PromptTemplate)
                .filter(
                    PromptTemplate.id == config.prompt_template_id,
                    PromptTemplate.is_active == True,
                )
                .first()
            )
            if template:
                return template.body

        return None

    def _resolve_system_default(
        self,
        db: Session,
        use_case: str,
    ) -> Optional[str]:
        template = (
            db.query(PromptTemplate)
            .filter(
                PromptTemplate.use_case == use_case,
                PromptTemplate.is_system == True,
                PromptTemplate.is_active == True,
            )
            .first()
        )
        return template.body if template else None
