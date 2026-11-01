"""Typed, schema-validated chat results.

Every assistant turn is exactly one of:
  education            approved-source answer (AI-written or verbatim quote)
  needs_clinician      personal judgment / unverified device / non-urgent flag
  source_unavailable   no approved clinic source covers the question
  urgent_contact_path  crisis, emergency or urgent red flag: clinic route first
A reply that fails validation is replaced by a safe source_unavailable result.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)
ResultType = Literal["education", "needs_clinician", "source_unavailable", "urgent_contact_path"]


class SourceCard(BaseModel):
    n: int = Field(ge=1)
    title: str = Field(min_length=1)
    kind: str
    version: int = Field(ge=1)
    reviewer: Optional[str] = None
    approved_at: Optional[str] = None
    segment: int = Field(ge=1)
    segments: int = Field(ge=1)
    is_demo: bool
    item_id: str
    video_id: Optional[str] = None
    excerpt: Optional[str] = Field(None, max_length=300)  # the approved passage the answer drew on


class ContactPath(BaseModel):
    label: str
    detail: Optional[str] = None
    hours: Optional[str] = None


class ChatResult(BaseModel):
    type: ResultType
    text: str = Field(min_length=1, max_length=8000)
    provenance: Literal["ai_generated", "source_quote", "clinic_configured"]
    sources: List[SourceCard] = []
    contact: Optional[ContactPath] = None
    handoff_offered: bool = False
    reason: Optional[str] = None  # e.g. device_unverified, personal_judgment, red_flag

    @model_validator(mode="after")
    def _rules(self):
        if self.type == "education" and not self.sources:
            raise ValueError("education results must cite at least one approved source")
        if self.type != "education" and self.provenance != "clinic_configured":
            raise ValueError("only education results may be AI-generated or quoted")
        if self.type == "urgent_contact_path" and self.sources:
            raise ValueError("urgent results carry the clinic route, not sources")
        return self


SAFE_FALLBACK = ("I can't give a reliable answer to that here. Please use “Ask my care team”, "
                 "or your clinic's usual contact route if it is urgent.")


def build(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return ChatResult(**data).model_dump()
    except ValidationError as exc:
        logger.error("care.result schema violation: %s", [e["msg"] for e in exc.errors()])
        return ChatResult(type="source_unavailable", text=SAFE_FALLBACK, provenance="clinic_configured",
                          handoff_offered=True, reason="schema_violation").model_dump()
