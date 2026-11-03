"""Clinic-scoped peer community endpoints. All live under /api/care/c/{slug}/community so the
real-patient-data gate covers them like other patient routes."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import get_current_user
from app.services.care import community as cm

router = APIRouter(prefix="/api/care/c/{clinic_slug}/community", tags=["care-community"])


class NickBody(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=40)


class PostBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    parent_id: Optional[uuid.UUID] = None


class ReactBody(BaseModel):
    kind: str = Field(..., max_length=20)


class ReportBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=300)


class ModerateBody(BaseModel):
    action: str = Field(..., max_length=10)


def _ctx(clinic_slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return cm.member(db, user, clinic_slug)


@router.get("")
def overview(ctx=Depends(_ctx), db: Session = Depends(get_db)):
    return cm.overview(db, ctx)


@router.put("/profile")
def set_profile(body: NickBody, ctx=Depends(_ctx), db: Session = Depends(get_db)):
    return cm.set_nickname(db, ctx, body.nickname)


@router.get("/spaces/{space}")
def space(space: str, ctx=Depends(_ctx), db: Session = Depends(get_db)):
    return cm.space_view(db, ctx, space)


@router.post("/spaces/{space}/posts", status_code=201)
def post(space: str, body: PostBody, ctx=Depends(_ctx), db: Session = Depends(get_db)):
    return cm.create_post(db, ctx, space, body.body, body.parent_id)


@router.post("/posts/{post_id}/reactions")
def react(post_id: uuid.UUID, body: ReactBody, ctx=Depends(_ctx), db: Session = Depends(get_db)):
    return cm.react(db, ctx, post_id, body.kind)


@router.post("/posts/{post_id}/report", status_code=201)
def report(post_id: uuid.UUID, body: ReportBody, ctx=Depends(_ctx), db: Session = Depends(get_db)):
    return cm.report(db, ctx, post_id, body.reason)


@router.get("/moderation")
def moderation(ctx=Depends(_ctx), db: Session = Depends(get_db)):
    return cm.queue(db, ctx)


@router.post("/posts/{post_id}/moderate")
def moderate(post_id: uuid.UUID, body: ModerateBody, ctx=Depends(_ctx), db: Session = Depends(get_db)):
    return cm.moderate(db, ctx, post_id, body.action)
