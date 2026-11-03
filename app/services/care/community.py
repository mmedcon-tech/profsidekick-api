"""Clinic-scoped peer community.

Rules that matter:
- Membership (an enrollment at the clinic, or a clinic staff row) is checked on every call; anyone else gets 404.
- People appear only under a nickname they choose. Real names, usernames and emails are never returned.
- Community posts are peer content. They are never indexed, never passed to AI retrieval, and never written
  to Patient Care Memory. Nothing in the AI chat path reads these tables.
- The clinician / moderator badge is set server-side from the staff row; a patient cannot claim it.
- Posts that look like dose or medication questions are flagged so the app can point to "Ask my care team".
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.database.models import (CareCommunityPost, CareCommunityProfile, CareCommunityReaction, CareCommunityReport,
                                 CareCommunitySpace, Clinic, ClinicStaff, User)
from app.services.care import access as acl
from app.services.care.agent_access import enrolled_at

DEFAULT_SPACES = [
    ("starting-ivf", "Starting IVF", "First consultations, tests and the weeks before treatment begins."),
    ("stimulation", "Stimulation and monitoring", "Day-to-day life during injections, scans and appointments."),
    ("two-week-wait", "Two-week wait", "The time between transfer and the test. Come as you are."),
    ("supporters", "Supporters", "For partners, friends and family who are there alongside someone."),
    ("work-and-life", "Work and everyday life", "Juggling treatment with work, travel plans and the rest of life."),
]
REACTIONS = ("heart", "hug", "same")
GUIDELINES = [
    "Be kind. Everyone here is going through something, and journeys look different.",
    "Use your nickname. Don't share your real name, phone number, address or anything that could identify you or someone else.",
    "Share experiences, not medical instructions. For questions about your own medicines, doses or results, use “Ask my care team”.",
    "No selling, fundraising or links to products or clinics.",
    "Members of your care team can carry a Clinician or Moderator badge. Nobody else can.",
    "If something worries you, use Report. Moderators from your clinic review reports and can hide posts.",
    "If you feel unsafe or in crisis, contact your clinic, your doctor or emergency services. This space is not monitored around the clock.",
]
MEDICAL = re.compile(
    r"\b\d+(\.\d+)?\s*(mg|mcg|µg|iu|ml|units?)\b|\b(dose|dosage|how much (should|do) i (take|inject)|"
    r"should i (take|stop|skip|double|increase|reduce)|missed (my|a) (dose|injection|shot)|"
    r"progesterone|gonal|menopur|cetrotide|ovitrelle|orgalutran|estradiol|medication|medicine)\b", re.I)
_NICK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{1,29}$")
_MOD_PERMS = ("can_manage", "can_approve")


def _now():
    return datetime.utcnow()


class Ctx:
    def __init__(self, clinic: Clinic, user: User, staff: Optional[ClinicStaff]):
        self.clinic, self.user, self.staff = clinic, user, staff

    @property
    def can_moderate(self) -> bool:
        return bool(self.staff and any(getattr(self.staff, p) for p in _MOD_PERMS))

    @property
    def badge(self) -> Optional[str]:
        if not self.staff:
            return None
        if self.staff.can_approve:
            return "clinician"
        if self.staff.can_manage:
            return "moderator"
        return None


def member(db: DBSession, user: User, clinic_slug: str) -> Ctx:
    """Every community call starts here: enrolled patients/supporters or clinic staff only."""
    clinic = acl.get_clinic(db, clinic_slug)
    staff = acl.staff_row(db, user, clinic.id)
    if not staff and not enrolled_at(db, user.id, clinic.id):
        raise acl.not_found("Clinic not found")
    return Ctx(clinic, user, staff)


def require_moderator(ctx: Ctx) -> None:
    if not ctx.can_moderate:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Moderators only")


def ensure_spaces(db: DBSession, clinic: Clinic) -> List[CareCommunitySpace]:
    rows = db.query(CareCommunitySpace).filter_by(clinic_id=clinic.id).order_by(CareCommunitySpace.sort).all()
    if rows:
        return rows
    for i, (slug, name, desc) in enumerate(DEFAULT_SPACES):
        db.add(CareCommunitySpace(id=uuid.uuid4(), clinic_id=clinic.id, slug=slug, name=name, description=desc, sort=i))
    db.commit()
    return db.query(CareCommunitySpace).filter_by(clinic_id=clinic.id).order_by(CareCommunitySpace.sort).all()


def profile(db: DBSession, ctx: Ctx) -> Optional[CareCommunityProfile]:
    return db.query(CareCommunityProfile).filter_by(clinic_id=ctx.clinic.id, user_id=ctx.user.id).first()


def set_nickname(db: DBSession, ctx: Ctx, nickname: str) -> Dict[str, Any]:
    nick = " ".join((nickname or "").split())
    if not _NICK.match(nick):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Nicknames are 2-30 letters, numbers, spaces, dots, dashes or underscores.")
    u = ctx.user
    first, last = (u.first_name or "").strip().lower(), (u.last_name or "").strip().lower()
    real = {(u.username or "").lower(), (u.email or "").split("@")[0].lower(), first, f"{first} {last}".strip()} - {""}
    if nick.lower() in real:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Pick a nickname that isn't your real name or username.")
    clash = db.query(CareCommunityProfile).filter_by(clinic_id=ctx.clinic.id, nickname_key=nick.lower()).first()
    if clash and clash.user_id != ctx.user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "That nickname is taken in this community.")
    p = profile(db, ctx)
    if p:
        p.nickname, p.nickname_key = nick, nick.lower()
    else:
        p = CareCommunityProfile(id=uuid.uuid4(), clinic_id=ctx.clinic.id, user_id=ctx.user.id,
                                 nickname=nick, nickname_key=nick.lower())
        db.add(p)
    db.commit()
    return {"nickname": p.nickname}


def overview(db: DBSession, ctx: Ctx) -> Dict[str, Any]:
    spaces = ensure_spaces(db, ctx.clinic)
    p = profile(db, ctx)
    counts = {}
    for s in spaces:
        counts[s.id] = db.query(CareCommunityPost).filter_by(space_id=s.id, parent_id=None, status="visible").count()
    return {
        "clinic": {"slug": ctx.clinic.slug, "name": ctx.clinic.name},
        "me": {"nickname": p.nickname if p else None, "badge": ctx.badge, "can_moderate": ctx.can_moderate},
        "spaces": [{"slug": s.slug, "name": s.name, "description": s.description, "posts": counts[s.id]} for s in spaces],
        "guidelines": GUIDELINES,
    }


def _space(db, ctx: Ctx, slug: str) -> CareCommunitySpace:
    ensure_spaces(db, ctx.clinic)
    s = db.query(CareCommunitySpace).filter_by(clinic_id=ctx.clinic.id, slug=slug).first()
    if not s:
        raise acl.not_found("Space not found")
    return s


def _post(db, ctx: Ctx, post_id) -> CareCommunityPost:
    p = db.query(CareCommunityPost).filter_by(id=post_id, clinic_id=ctx.clinic.id).first()
    if not p:
        raise acl.not_found("Post not found")
    return p


def _out(db, ctx: Ctx, p: CareCommunityPost, nick: Dict, mine: set, counts: Dict) -> Dict[str, Any]:
    hidden = p.status != "visible"
    return {
        "id": str(p.id), "parent_id": str(p.parent_id) if p.parent_id else None,
        "author": nick.get(p.profile_id, "Member"), "badge": p.badge,
        "body": None if hidden and not ctx.can_moderate else p.body,
        "hidden": hidden, "medical_flag": p.medical_flag, "fictional": p.is_fictional,
        "mine": p.author_user_id == ctx.user.id,
        "reactions": {k: counts.get((p.id, k), 0) for k in REACTIONS},
        "my_reactions": sorted(k for (pid, k) in mine if pid == p.id),
        "created_at": p.created_at.isoformat() + "Z",
    }


def _render(db, ctx: Ctx, posts: List[CareCommunityPost]) -> List[Dict[str, Any]]:
    ids = [p.id for p in posts]
    nick = {r.id: r.nickname for r in db.query(CareCommunityProfile).filter(
        CareCommunityProfile.id.in_({p.profile_id for p in posts})).all()} if posts else {}
    counts, mine = {}, set()
    if ids:
        for r in db.query(CareCommunityReaction).filter(CareCommunityReaction.post_id.in_(ids)).all():
            counts[(r.post_id, r.kind)] = counts.get((r.post_id, r.kind), 0) + 1
            if r.user_id == ctx.user.id:
                mine.add((r.post_id, r.kind))
    return [_out(db, ctx, p, nick, mine, counts) for p in posts]


def space_view(db: DBSession, ctx: Ctx, slug: str) -> Dict[str, Any]:
    s = _space(db, ctx, slug)
    q = db.query(CareCommunityPost).filter_by(space_id=s.id)
    if not ctx.can_moderate:
        q = q.filter(CareCommunityPost.status == "visible")
    posts = q.order_by(CareCommunityPost.created_at.desc()).limit(200).all()
    top = [p for p in posts if p.parent_id is None]
    replies = sorted([p for p in posts if p.parent_id is not None], key=lambda p: p.created_at)
    rendered = {r["id"]: r for r in _render(db, ctx, top + replies)}
    threads = []
    for p in top:
        t = dict(rendered[str(p.id)])
        t["replies"] = [rendered[str(r.id)] for r in replies if r.parent_id == p.id]
        threads.append(t)
    return {"space": {"slug": s.slug, "name": s.name, "description": s.description}, "threads": threads}


def create_post(db: DBSession, ctx: Ctx, slug: str, body: str, parent_id=None, fictional: bool = False) -> Dict:
    s = _space(db, ctx, slug)
    p = profile(db, ctx)
    if not p:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "nickname_required",
                                                       "message": "Choose a nickname before posting."})
    text = (body or "").strip()
    if not 1 <= len(text) <= 4000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Posts are 1-4000 characters.")
    if parent_id:
        parent = _post(db, ctx, parent_id)
        if parent.space_id != s.id or parent.parent_id is not None or parent.status != "visible":
            raise acl.not_found("Post not found")
    row = CareCommunityPost(id=uuid.uuid4(), clinic_id=ctx.clinic.id, space_id=s.id, parent_id=parent_id,
                            profile_id=p.id, author_user_id=ctx.user.id, body=text, badge=ctx.badge,
                            medical_flag=bool(MEDICAL.search(text)), is_fictional=fictional, created_at=_now())
    db.add(row)
    db.commit()
    return _render(db, ctx, [row])[0]


def react(db: DBSession, ctx: Ctx, post_id, kind: str) -> Dict:
    if kind not in REACTIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown reaction")
    p = _post(db, ctx, post_id)
    if p.status != "visible":
        raise acl.not_found("Post not found")
    r = db.query(CareCommunityReaction).filter_by(post_id=p.id, user_id=ctx.user.id, kind=kind).first()
    if r:
        db.delete(r)
    else:
        db.add(CareCommunityReaction(id=uuid.uuid4(), post_id=p.id, user_id=ctx.user.id, kind=kind))
    db.commit()
    return _render(db, ctx, [p])[0]


def report(db: DBSession, ctx: Ctx, post_id, reason: Optional[str]) -> Dict:
    p = _post(db, ctx, post_id)
    db.add(CareCommunityReport(id=uuid.uuid4(), clinic_id=ctx.clinic.id, post_id=p.id,
                               reporter_user_id=ctx.user.id, reason=(reason or "")[:300] or None))
    db.commit()
    return {"reported": True}


def queue(db: DBSession, ctx: Ctx) -> Dict:
    require_moderator(ctx)
    open_reports = (db.query(CareCommunityReport)
                    .filter_by(clinic_id=ctx.clinic.id, resolved_at=None).order_by(CareCommunityReport.created_at).all())
    hidden = db.query(CareCommunityPost).filter_by(clinic_id=ctx.clinic.id, status="hidden").all()
    by_post: Dict[Any, Dict] = {}
    for r in open_reports:
        e = by_post.setdefault(r.post_id, {"reasons": [], "reports": 0})
        e["reports"] += 1
        if r.reason:
            e["reasons"].append(r.reason)
    posts = db.query(CareCommunityPost).filter(
        CareCommunityPost.id.in_(set(by_post) | {h.id for h in hidden})).all() if (by_post or hidden) else []
    spaces = {s.id: s.slug for s in db.query(CareCommunitySpace).filter_by(clinic_id=ctx.clinic.id).all()}
    items = []
    for p, out in zip(posts, _render(db, ctx, posts)):
        out.update(by_post.get(p.id, {"reasons": [], "reports": 0}), space=spaces.get(p.space_id))
        items.append(out)
    items.sort(key=lambda i: (-i["reports"], i["created_at"]))
    return {"items": items}


def moderate(db: DBSession, ctx: Ctx, post_id, action: str) -> Dict:
    require_moderator(ctx)
    p = _post(db, ctx, post_id)
    if action not in ("hide", "restore", "dismiss"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown action")
    if action == "hide":
        p.status = "hidden"
    elif action == "restore":
        p.status = "visible"
    p.moderated_by, p.moderated_at = ctx.user.id, _now()
    resolution = {"hide": "hidden", "restore": "restored", "dismiss": "dismissed"}[action]
    for r in db.query(CareCommunityReport).filter_by(post_id=p.id, resolved_at=None).all():
        r.resolved_at, r.resolution = _now(), resolution
    db.commit()
    return _render(db, ctx, [p])[0]
