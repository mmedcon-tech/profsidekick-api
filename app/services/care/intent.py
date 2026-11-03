"""Intent router, run before safety routing and document search: greetings and
"is the model working?" questions get a short fixed reply, never a document passage."""
from __future__ import annotations

import re
from typing import Optional

GREETING, MODEL_STATUS = "greeting", "model_status"
_GREET = re.compile(r"^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|greetings|bonjour|hola)\b[\s,.!?]*"
                    r"(there|dr\.? ?avery|doctor|avery|everyone)?[\s,.!?]*$", re.I)
_THANKS = re.compile(r"^\s*(thanks|thank you|thx|ok(ay)? thanks?)[\s,.!?]*(so much|a lot)?[\s,.!?]*$", re.I)
_STATUS = re.compile(r"\b((is|are) (the |your )?(ai|model|assistant|bot|chat(bot)?|system|you) (working|online|available|up|ok|on|running)"
                     r"|are you (working|there|online|real|a bot|an ai)|is (this|it) working|can you (hear|answer) me"
                     r"|(model|ai|chat) (down|broken|not working))\b", re.I)


def classify(text: str) -> Optional[str]:
    t = (text or "").strip()
    if len(t) > 120:
        return None
    if _STATUS.search(t):
        return MODEL_STATUS
    if _GREET.match(t) or _THANKS.match(t):
        return GREETING
    return None


def assistant_name(persona) -> str:
    name = getattr(persona, "name", None)
    return f"{name}'s AI assistant" if name else "your clinic's AI assistant"


def welcome(persona, clinic, first_name: Optional[str], thanks: bool = False) -> str:
    if thanks:
        return "You're welcome. Ask me anything about your clinic's information, or use \u201cAsk my care team\u201d for anything personal."
    hi = f"Hello {first_name}." if first_name else "Hello."
    return (f"{hi} I'm {assistant_name(persona)} at {clinic.name}. I can explain your clinic's approved information "
            "about your treatment. For your own doses, results or symptoms, I'll connect you with your care team.")


def status_reply(ok: bool) -> str:
    if ok:
        return "Yes, I'm working. Ask me a question about your treatment and I'll answer from your clinic's approved information."
    return ("My AI answers are paused right now. I can still share answers from your clinic's FAQ, "
            "and your care team can help with anything else through \u201cAsk my care team\u201d.")
