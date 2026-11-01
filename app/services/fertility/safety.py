"""
Rule-based safety classification run BEFORE answer generation.

Categories (spec §12):
  general_education, clinic_specific_instruction, patient_specific_decision,
  time_sensitive_medication, emergency  (+ crisis, partner_authorization)

Emergency, crisis, time-sensitive medication and partner-authorization turns
get a fixed, clinician-reviewable response (from the KB's answer patterns);
the LLM is not asked to improvise them. Escalation is only ever simulated in
the demo and labelled as such.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

GENERAL = "general_education"
CLINIC = "clinic_specific_instruction"
PATIENT_DECISION = "patient_specific_decision"
MEDICATION = "time_sensitive_medication"
EMERGENCY = "emergency"
CRISIS = "crisis"
PARTNER_AUTH = "partner_authorization"

DETERMINISTIC = {EMERGENCY, CRISIS, MEDICATION, PARTNER_AUTH}

SIMULATED_LABEL = "Simulated for this demo — no message was sent to a real clinic or nurse."


@dataclass
class SafetyResult:
    category: str
    subtype: Optional[str] = None
    risk_level: str = "education"  # education | routine | urgent | emergency
    matched: List[str] = field(default_factory=list)
    escalation_offered: bool = False
    escalation_label: Optional[str] = None
    fixed_response: Optional[str] = None

    @property
    def deterministic(self) -> bool:
        return self.category in DETERMINISTIC

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("fixed_response", None)
        d["deterministic"] = self.deterministic
        return d


def _has(text: str, *patterns: str) -> List[str]:
    return [p for p in patterns if re.search(p, text)]


_CRISIS = (r"kill myself", r"suicid", r"self[- ]harm", r"hurt myself", r"end my life", r"don'?t want to (live|be alive)", r"no reason to live")
_EMERGENCY = (
    r"can'?t breathe", r"short(ness)? of breath", r"(trouble|difficulty) breathing", r"struggling to breathe",
    r"faint", r"passed out", r"pass out", r"chest pain", r"heavy bleeding", r"bleeding heavily", r"soak(ing|ed) (a|through)",
    r"severe (abdominal|pelvic|stomach|belly)? ?pain", r"(abdominal|pelvic|stomach) pain.*(severe|unbearable|worse)", r"worsening pain",
    r"one[- ]sided (severe )?(pelvic )?pain", r"shoulder[- ]tip", r"torsion", r"unbearable pain", r"throat (is )?swell", r"anaphyla",
)
_SWELLING = (r"swollen", r"swelling", r"huge", r"very bloated", r"distended", r"tight")
_URINE = (r"urinat", r"\bpee", r"urine")
_MEDICATION_OBJ = r"(inject|injection|shot|dose|trigger|medication|medicine|pen|progesterone|syringe|needle|vial)"
_MEDICATION_PROBLEMS = (
    r"\bmissed\b", r"\bforgot", r"\blate\b", r"half (the|of)", r"\bpartial", r"leak", r"not sure how much",
    r"stopped halfway", r"pen (stopped|jammed|broke|malfunction)", r"malfunction", r"wrong (dose|needle|medication|drug|time|location|site)",
    r"\bdouble\b", r"\brepeat\b", r"inject more", r"give (the )?rest", r"top (it )?up", r"pulled out early", r"unrefrigerated",
    r"(left )?out of the fridge", r"dropped the vial", r"can'?t remember whether", r"conflict", r"different directions",
    r"dose changed", r"\bstop (taking|the|my)?\s*(progesterone|medication|medicine|support)", r"stop progesterone", r"extra dose",
    r"combine injections", r"reuse a needle",
)
_PARTNER_PRIVATE = (
    r"\bher (results?|hormone|labs?|lab results|estradiol|hcg|amh|chart|record|scan|test)", r"nora'?s", r"tell me (her|my partner'?s|my wife'?s)",
    r"(my partner'?s|my wife'?s|my girlfriend'?s) (results?|hormone|labs?|chart|record|estradiol|hcg|amh)",
)
_PATIENT_DECISION = (
    r"\bmy (chance|chances|odds)", r"success rate", r"will (it|this|ivf) work", r"should i (do|have|choose|get|start|freeze|transfer|continue|pause)",
    r"my (results?|estradiol|hcg|amh|afc|fsh|embryo grade|scan)", r"is my .* (normal|good|bad)", r"how many eggs should i",
    r"should we (transfer|test|freeze)", r"diagnos",
)
_CLINIC = (
    r"my clinic", r"before anesthesia", r"refundable", r"\bfees?\b", r"storage cost", r"my (plan|protocol|schedule|dose|appointment)",
    r"clinic agreement", r"clinic'?s",
)


def classify(text: str, role: str = "patient") -> SafetyResult:
    t = (text or "").lower()

    m = _has(t, *_CRISIS)
    if m:
        return SafetyResult(CRISIS, "psychological_crisis", "emergency", m, True, SIMULATED_LABEL, _CRISIS_REPLY)

    m = _has(t, *_EMERGENCY)
    swell, urine = _has(t, *_SWELLING), _has(t, *_URINE)
    if swell and urine:
        return SafetyResult(EMERGENCY, "ohss_warning", "emergency", swell + urine, True, SIMULATED_LABEL, _OHSS_REPLY)
    if m:
        sub = "post_transfer_or_pregnancy" if re.search(r"(positive|pregnan|transfer)", t) else "acute_symptom"
        return SafetyResult(EMERGENCY, sub, "emergency", m, True, SIMULATED_LABEL, _EMERGENCY_REPLY)

    if role == "partner":
        m = _has(t, *_PARTNER_PRIVATE)
        if m:
            return SafetyResult(PARTNER_AUTH, "private_results", "routine", m, False, None, _PARTNER_REPLY)

    if re.search(_MEDICATION_OBJ, t) or re.search(r"\b(stop|stopping)\b.*(progesterone|medication)", t):
        m = _has(t, *_MEDICATION_PROBLEMS)
        if m:
            sub, reply = _medication_reply(t)
            return SafetyResult(MEDICATION, sub, "urgent", m, True, SIMULATED_LABEL, reply)

    m = _has(t, *_PATIENT_DECISION)
    if m:
        return SafetyResult(PATIENT_DECISION, None, "routine", m)

    m = _has(t, *_CLINIC)
    if m:
        return SafetyResult(CLINIC, None, "routine", m)

    return SafetyResult(GENERAL)


def _medication_reply(t: str) -> tuple[str, str]:
    if "trigger" in t:
        return "late_or_uncertain_trigger", (
            "Trigger timing matters, and I can't determine whether a delay is safe. Please contact your "
            "fertility clinic's urgent number now. I can prepare a message with the exact time and medication "
            "for you — in this demo, sending is only simulated."
        )
    if re.search(r"conflict|different directions|dose changed", t):
        return "conflicting_instructions", (
            "Thanks for flagging this. I can see the instructions don't agree, and I won't choose between them. "
            "Please don't rely on the older schedule — let's verify the latest signed order with your fertility "
            "team before you take the medication."
        )
    if re.search(r"stop", t) and re.search(r"progesterone|medication|support", t):
        return "stopping_medication", (
            "Please don't stop prescribed medication based on this chat. An early home test may not be definitive. "
            "Follow your clinic's testing plan and contact your team for medication instructions. I can help you "
            "draft that message."
        )
    if re.search(r"unrefrigerated|out of the fridge|dropped the vial", t):
        return "storage_failure", (
            "I can't tell whether that medication is still usable. Please don't use it until your clinic or "
            "pharmacist confirms — contact them now so your schedule isn't affected. I can help you prepare the details."
        )
    return "dose_uncertainty", (
        "Thanks for checking before giving more. Please don't repeat, double or top up the dose until your "
        "fertility team confirms what to do — I can't tell how much was delivered from a description. "
        "Contact your clinic's urgent line now. I can help prepare a message with the medication, prescribed "
        "dose, time, device and what happened (in this demo, sending is only simulated)."
    )


_OHSS_REPLY = (
    "I'm glad you told me. Marked swelling with much less urine during or after stimulation can be a warning sign "
    "and needs urgent medical assessment. Please contact your clinic's urgent team now, or use local emergency "
    "services if you feel seriously unwell. I can't safely assume this is just bloating. I can help summarise your symptoms."
)
_EMERGENCY_REPLY = (
    "This could need urgent medical attention. Please contact your fertility clinic's urgent line now, and if you "
    "feel seriously unwell — trouble breathing, fainting, chest pain, heavy bleeding or severe pain — call your local "
    "emergency number or go to the nearest emergency department. I can help summarise your symptoms for the team."
)
_CRISIS_REPLY = (
    "I'm really sorry you're feeling this way, and I'm glad you said it. You deserve support from a person right now. "
    "If you might act on these thoughts, please call your local emergency number or a crisis line immediately. "
    "If you can, reach out to someone you trust and to your clinic's counselling team. I'm an AI and can't provide crisis care."
)
_PARTNER_REPLY = (
    "I can explain what these tests and results are used for in general. To share her personal results, I'd need "
    "her authorization, and she hasn't granted that in this app. Would you like a general explanation instead?"
)
