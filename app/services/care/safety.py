"""Program-agnostic safety routing, run before any answer generation.

Order: crisis → clinic-configured red flags (approved rules only) → generic
emergency signs → personal clinical judgment (doses, injection timing,
titration, procedure suitability, stopping/starting medicine) → education.
Every non-education route gets a fixed reply built from clinic configuration;
the model never improvises thresholds or decisions.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.database.models import CareProgram, Clinic, RedFlagRule
from app.services.fertility.safety import _CRISIS, _EMERGENCY

EDUCATION, RED_FLAG, EMERGENCY, CRISIS, PERSONAL = "education", "red_flag", "emergency", "crisis", "personal_judgment"

_PERSONAL = (
    r"\b(dose|doses|dosage|dosing|how (much|many) (should|do|can) i (take|inject|use))\b",
    r"\b(increase|decrease|raise|lower|double|skip|change|adjust)\b.{0,25}\b(dose|medication|medicine|injection|shot)",
    r"\btitrat", r"\b(will|could|can|would|does|might) (this|it|that|the \w+)\b.{0,40}\b(harm|hurt|damage|affect)\b",
    r"\bshould i (take|inject|use) (it|this|my|the)\b", r"\bwhen should i (inject|take|have my)\b", r"\b(what|which) (day|time) should i inject\b",
    r"\b(am i|would i be|is it right for me to be) (a )?(good |suitable |right )?(candidate|suitable|eligible)\b",
    r"\b(should|can) i (stop|start|switch|restart|come off|go on)\b",
    r"\bis (it|this|the procedure|surgery) (safe|right|ok|okay) for me\b", r"\bshould i (have|get|do) (the|this|a)\b.{0,40}(surgery|procedure|filler|injection|treatment)",
)

# General lifestyle questions ("should I stop smoking before IVF?") are education, not a
# personal treatment decision, unless they also mention medicine, doses or treatment.
_LIFESTYLE = r"\b(should|can) i (stop|start|cut down|give up|quit|reduce|keep)\b.{0,20}\b(smok\w*|vap\w*|cigarettes?|drink\w*|alcohol|wine|beer|caffeine|coffee|tea|exercis\w*|running|gym|diet\w*|eating|sugar|sex)\b"
_TREATMENT = r"\b(dose|doses|dosage|medication|medications|medicine|meds|pills?|tablets?|injections?|shots?|drugs?|hormones?|treatment|ivf|cycle|transfer|procedure|stims?|progesterone|estrogen|oestrogen)\b"


def _lifestyle_only(t: str) -> bool:
    if not re.search(_LIFESTYLE, t):
        return False
    rest = re.sub(_LIFESTYLE, " ", t)
    rest = re.sub(r"\b(before|during|while|for|on|doing|having)\s+(ivf|treatment|a cycle|my cycle|the cycle)\b", " ", rest)
    return not re.search(_TREATMENT, rest)


@dataclass
class Route:
    kind: str
    matched: List[str] = field(default_factory=list)
    urgency: str = "education"
    rule_id: Optional[str] = None
    contact_route: Optional[str] = None
    reply: Optional[str] = None
    handoff_offered: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("reply", None)
        d["deterministic"] = self.kind != EDUCATION
        return d


def _hits(text: str, patterns) -> List[str]:
    return [p for p in patterns if re.search(p, text)]


def route_info(clinic: Clinic, key: Optional[str]) -> Optional[Dict[str, Any]]:
    routes = clinic.contact_routes or []
    for r in routes:
        if r.get("key") == key:
            return r
    return None


def _route_line(clinic: Clinic, key: Optional[str]) -> str:
    r = route_info(clinic, key)
    if not r:
        return "Contact your clinic using the details they gave you."
    hours = f" ({r['hours']})" if r.get("hours") else ""
    return f"{r.get('label', 'Clinic contact')}: {r.get('detail', '')}{hours}".strip()


def _expectation(clinic: Clinic) -> str:
    return clinic.response_expectation or "Your clinic sets its own response times; this assistant is not monitored around the clock."


def match_red_flags(db, program: CareProgram, text: str, visible_course_ids) -> Optional[RedFlagRule]:
    rules = (db.query(RedFlagRule)
             .filter(RedFlagRule.program_id == program.id, RedFlagRule.clinic_id == program.clinic_ref_id,
                     RedFlagRule.status == "approved").all())
    order = {"emergency": 0, "urgent": 1, "same_day": 2, "routine": 3}
    hits = []
    for r in rules:
        if r.course_id and r.course_id not in visible_course_ids:
            continue
        terms = [t.strip().lower() for t in (r.match_terms or []) if t and t.strip()]
        if any(t in text for t in terms):
            hits.append(r)
    hits.sort(key=lambda r: order.get(r.urgency, 9))
    return hits[0] if hits else None


def classify(db, clinic: Clinic, program: CareProgram, text: str, visible_course_ids) -> Route:
    t = (text or "").lower()
    m = _hits(t, _CRISIS)
    if m:
        return Route(CRISIS, m, "emergency", reply=(
            "I'm really sorry you're feeling this way. If you might act on these thoughts or are in danger, call your "
            "local emergency number now (112 in the EU, 911 in the US) or a crisis line. You deserve support from a "
            "person right now; this assistant can't provide that."), handoff_offered=True)
    rule = match_red_flags(db, program, t, visible_course_ids)
    if rule:
        when = {"emergency": "Call your local emergency number now if this is happening.",
                "urgent": "Treat this as urgent.", "same_day": "Contact the clinic today.",
                "routine": "Mention this to your clinic."}.get(rule.urgency, "")
        return Route(RED_FLAG, [rule.symptom], rule.urgency, str(rule.id), rule.contact_route, handoff_offered=True, reply=(
            f"What you describe matches a warning sign your clinic has listed: **{rule.symptom}**. {when}\n\n"
            f"Your clinic's instruction: {rule.clinic_action}\n\n{_route_line(clinic, rule.contact_route)}\n\n"
            f"{_expectation(clinic)} Please don't wait for a reply here."))
    m = _hits(t, _EMERGENCY)
    if m:
        return Route(EMERGENCY, m, "emergency", handoff_offered=True, reply=(
            "Some of what you describe can be serious. If symptoms are severe or getting worse, call your local "
            "emergency number now (112 in the EU, 911 in the US). Otherwise contact your clinic directly.\n\n"
            f"{_route_line(clinic, 'urgent')}\n\n{_expectation(clinic)}"))
    m = _hits(t, _PERSONAL)
    if m and _lifestyle_only(t):
        m = []
    if m:
        return Route(PERSONAL, m, "routine", handoff_offered=True, contact_route="routine", reply=(
            "That's a decision your care team needs to make with you. I can't work out doses, injection timing, "
            "dose changes or whether a procedure suits you. I can send this question to your care team for review "
            "(use “Ask my care team”), and in the meantime the education material in this program may help you "
            f"prepare.\n\n{_expectation(clinic)}"))
    return Route(EDUCATION)
