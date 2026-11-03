"""Deterministic local adapter (no network). Used for CI and to prove provider switching.

It answers only from the SOURCES block it was given, quoting the first source and citing it,
so citation resolution, permissions and escalation can be compared across providers."""
from __future__ import annotations

import hashlib
import json
import re
from typing import AsyncIterator, Dict, List, Optional, Type

from pydantic import BaseModel

from app.services.ai import errors
from app.services.ai.base import Generation, parse_structured

_SRC = re.compile(r"<<<SOURCE (\d+)[^>]*>>>\s*(.*?)\s*<<<END SOURCE \1>>>", re.S)


class LocalAdapter:
    id = "local"

    def __init__(self, fail_with: Optional[str] = None):
        self.fail_with = fail_with  # simulate an outage: "unavailable", "timeout", "quota"
        self.calls: List[Dict[str, object]] = []

    def _maybe_fail(self):
        if self.fail_with:
            raise {"unavailable": errors.Unavailable, "timeout": errors.Timeout,
                   "quota": errors.Quota}[self.fail_with](self.fail_with)

    async def generate(self, messages: List[Dict[str, str]], *, model: str, timeout: float,
                       temperature: float = 0.3, schema: Optional[Type[BaseModel]] = None) -> Generation:
        self.calls.append({"model": model, "n_messages": len(messages)})
        self._maybe_fail()
        system = messages[0]["content"] if messages else ""
        m = _SRC.search(system)
        if not m:
            text = "I don't have approved clinic material on that. Please use \u201cAsk my care team\u201d."
        else:
            body = re.sub(r"\s+", " ", m.group(2).split("\n", 1)[-1]).strip()
            first = re.split(r"(?<=[.!?])\s", body, maxsplit=2)
            text = " ".join(first[:2])[:600] + f" [{m.group(1)}]"
        if schema:
            text = json.dumps({"text": text})
        return Generation(text, self.id, model, parse_structured(text, schema))

    async def stream(self, messages, *, model: str, timeout: float, temperature: float = 0.3) -> AsyncIterator[str]:
        g = await self.generate(messages, model=model, timeout=timeout)
        for w in g.text.split(" "):
            yield w + " "

    def embed(self, texts: List[str], *, model: str, timeout: float) -> List[List[float]]:
        self._maybe_fail()
        out = []
        for t in texts:  # stable hashed bag-of-words, 1536 dims, unit length
            v = [0.0] * 1536
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 1536] += 1.0
            n = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / n for x in v])
        return out
