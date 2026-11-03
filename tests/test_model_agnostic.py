"""Model-agnostic layer: contract, registry eligibility, config-only switching, eligible-only
fallback, text-free operational log, citation resolution, hub export and reindex."""
import copy
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.database.models import CareContentChunk, CareContentItem, CareProgram
from app.services.ai import errors, registry, router
from app.services.ai.adapters.local_adapter import LocalAdapter
from app.services.care import content, guidance, health
from tests.test_care_integrity import WM, _approve_item
from tests.test_care_platform import _as, _enroll, _user, world  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CLINICAL = [*sorted((ROOT / "app/services/care").glob("*.py")), *sorted((ROOT / "app/services/fertility").glob("*.py")),
            *sorted((ROOT / "app/api/care").glob("*.py")), *sorted((ROOT / "app/mcp").glob("**/*.py"))]
OPS_ONLY = {"health.py"}  # provider health probes; not clinical workflow
SDK = re.compile(r"^\s*(from|import)\s+(openai|anthropic|google\.generativeai|google\.genai|elevenlabs|cohere|mistralai)\b", re.M)
MODEL = re.compile(r"['\"](gpt-[\w.\-]+|text-embedding-[\w\-]+|gemini-[\w.\-]+|claude-[\w.\-]+|eleven_[\w]+|whisper-1|tts-1)['\"]")


class FakeOpenAI(LocalAdapter):
    """Stands in for the OpenAI adapter in CI (no network): same contract, distinct wording."""
    id = "openai"

    async def generate(self, messages, *, model, timeout, temperature=0.3, schema=None):
        g = await super().generate(messages, model=model, timeout=timeout)
        g.provider, g.text = "openai", "In short: " + g.text
        return g


@pytest.fixture
def env(world, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(content, "_try_embed", lambda texts: None)
    monkeypatch.setattr(settings, "openai_api_key", "sk-" + "f" * 40)
    base = copy.deepcopy(registry.load())
    router.reset(); health.reset_breaker()
    oa, lo = FakeOpenAI(), LocalAdapter()
    router.install("openai", oa); router.install("local", lo)
    c, db, staff = world["client"], world["db"], world["staff"]
    _as(staff)
    pid = str(db.query(CareProgram).filter_by(slug="a-weight-management").first().id)
    _approve_item(c, pid, "Egg collection leaflet", "Egg collection is a short procedure under sedation. "
                  "A fine needle guided by ultrasound collects eggs from the ovaries.")
    pat = _user(db)
    _as(pat)
    _enroll(c, "demo-clinic-a", "a-weight-management")
    yield {"c": c, "db": db, "cfg": base, "openai": oa, "local": lo, "world": world}
    registry.set_config(base); router.reset(); health.reset_breaker()


def _use(cfg, generation, data_class=None):
    cfg = copy.deepcopy(cfg)
    cfg["routing"]["default"]["generation"] = generation
    registry.set_config(cfg)
    return cfg


FLOW = ["How is egg collection done?",
        "Is there a video showing how to do my injection?",
        "My leaflet says 0.5 mg but the nurse said 1 mg. Which dose should I take?"]


def _run(c):
    out = []
    for q in FLOW:
        d = c.post(f"{WM}/messages", json={"content": q}).json()
        r = d["result"]
        out.append({"type": r["type"], "handoff": r["handoff_offered"], "reason": r.get("reason"),
                    "route": d["route"]["kind"], "cites": [s["item_id"] for s in r.get("sources") or []],
                    "prov": r["provenance"], "provider": d["route"]["provider"].get("provider"), "text": r["text"]})
    return out


def test_no_model_names_or_sdk_imports_in_clinical_code():
    bad = []
    for f in CLINICAL:
        if f.name in OPS_ONLY:
            continue
        s = f.read_text()
        bad += [f"{f.relative_to(ROOT)}: sdk" for _ in SDK.findall(s)] + [f"{f.relative_to(ROOT)}: {m}" for m in MODEL.findall(s)]
    assert not bad, bad


def test_registry_is_valid_and_honest():
    cfg = registry.load()
    assert registry.validate(cfg) == []
    for p in ("openai", "elevenlabs", "liveavatar"):
        assert cfg["providers"][p]["agreements"]["baa"] == "unknown"
    assert registry.eligible(cfg, "openai", "generation", "phi") == "data_class_not_permitted"
    assert registry.eligible(cfg, "openai", "generation", "synthetic", "gpt-4.1") is None
    assert registry.eligible(cfg, "openai", "generation", "synthetic", "some-other-model") == "model_not_approved"
    assert registry.eligible(cfg, "openai", "transcription", "public_content") == "capability_not_enabled"
    assert registry.eligible(cfg, "liveavatar", "voice", "phi") == "data_class_not_permitted"
    # listing phi is not enough: a US provider also needs a signed BAA
    c2 = copy.deepcopy(cfg)
    c2["providers"]["openai"]["capabilities"]["generation"]["data_classes"].append("phi")
    assert registry.eligible(c2, "openai", "generation", "phi") == "baa_not_signed"
    # a provider's general approval never turns on a capability it doesn't list
    assert registry.eligible(cfg, "openai", "vendor_hosted_tools", "public_content") == "capability_not_enabled"


def test_switching_providers_by_config_keeps_permissions_citations_and_escalation(env):
    _use(env["cfg"], ["openai:gpt-4.1"])
    a = _run(env["c"])
    _use(env["cfg"], ["local:local-extractive-v1"])
    b = _run(env["c"])
    assert [x["provider"] for x in a] == ["openai", None, None] and [x["provider"] for x in b] == ["local", None, None]
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ("text", "provider")} for r in rows]  # noqa: E731
    assert strip(a) == strip(b)
    gen, video, dose = a
    assert gen["type"] == "education" and gen["prov"] == "ai_generated" and gen["cites"]
    assert video["type"] == "needs_clinician" and video["handoff"] and not video["cites"]  # no unverified video/technique
    assert dose["type"] == "needs_clinician" and dose["route"] == "personal_judgment" and dose["handoff"]
    assert len(env["openai"].calls) == 1 and len(env["local"].calls) == 1  # gated questions never reach a model


def test_outage_never_sends_patient_data_to_ineligible_fallback(env):
    db = env["db"]
    clinic = env["world"]["a"]
    clinic.is_demo = False; db.commit()  # real-patient clinic → data class phi
    cfg = _use(env["cfg"], ["local:local-extractive-v1", "openai:gpt-4.1"])
    env["local"].fail_with = "unavailable"
    r = env["c"].post(f"{WM}/messages", json={"content": "How is egg collection done?"}).json()
    assert env["openai"].calls == []  # OpenAI is not eligible for PHI: nothing was sent
    assert r["result"]["provenance"] == "source_quote" and r["result"]["sources"]
    # an independently eligible secondary is used
    cfg["providers"]["local_b"] = copy.deepcopy(cfg["providers"]["local"]); cfg["providers"]["local_b"]["adapter"] = "local_b"
    cfg["routing"]["default"]["generation"] = ["local:local-extractive-v1", "openai:gpt-4.1", "local_b:local-extractive-v1"]
    registry.set_config(cfg)
    second = LocalAdapter(); router.install("local_b", second)
    r = env["c"].post(f"{WM}/messages", json={"content": "How is egg collection done?"}).json()
    assert env["openai"].calls == [] and len(second.calls) == 1
    assert r["result"]["provenance"] == "ai_generated" and r["route"]["provider"]["fallback_reason"] == "unavailable"
    clinic.is_demo = True; db.commit()


def test_operational_log_contains_no_message_text(env, caplog):
    _use(env["cfg"], ["local:local-extractive-v1"])
    marker = "zebracorn" + uuid.uuid4().hex[:6]
    with caplog.at_level(logging.INFO, logger="myos.model_ops"):
        env["c"].post(f"{WM}/messages", json={"content": f"How is egg collection done {marker}?"})
    ops = [r.getMessage() for r in caplog.records if r.name == "myos.model_ops"]
    assert ops and all(marker not in m and "egg" not in m.lower() and "sedation" not in m for m in ops)
    assert any('"provider": "local"' in m and '"outcome": "ok"' in m for m in ops)


def test_invented_citations_are_removed():
    text, bad = guidance.resolve_citations("A [1]. B [7]. C [2].", 2)
    assert bad == [7] and "[7]" not in text and "[1]" in text and "[2]" in text


def test_error_mapping_into_myos_types():
    from app.services.ai.adapters.openai_adapter import map_error

    class E(Exception):
        def __init__(self, status=None, code=None):
            self.status_code, self.code = status, code

    assert isinstance(map_error(E(429, "insufficient_quota")), errors.Quota)
    assert isinstance(map_error(E(401)), errors.Auth)
    assert isinstance(map_error(E(429)), errors.RateLimited)
    assert isinstance(map_error(E(503)), errors.Unavailable)
    assert not errors.Quota().retryable and errors.Unavailable().retryable


def test_structured_output_validated():
    import asyncio

    from pydantic import BaseModel

    class Out(BaseModel):
        text: str

    msgs = [{"role": "system", "content": "<<<SOURCE 1>>> title: T (v1)\nEggs are collected. Done.\n<<<END SOURCE 1>>>"}]
    g = asyncio.run(LocalAdapter().generate(msgs, model="m", timeout=1, schema=Out))
    assert g.parsed and g.parsed["text"].endswith("[1]")


def test_effective_dates_hide_content(env):
    db = env["db"]
    items = db.query(CareContentItem).filter_by(title="Egg collection leaflet").all()
    for it in items:
        it.effective_to = datetime.utcnow() - timedelta(days=1)
    db.commit()
    r = env["c"].post(f"{WM}/messages", json={"content": "How is egg collection done?"}).json()["result"]
    assert not {s["item_id"] for s in r.get("sources") or []} & {str(i.id) for i in items}
    for it in items:
        it.effective_to = None
    db.commit()


def test_export_and_reindex_on_embedding_model_change(env, monkeypatch):
    from app.services.care import hub
    from app.services.fertility import knowledge

    db = env["db"]
    doc = hub.export_clinic(db, env["world"]["a"])
    assert doc["format"] == hub.EXPORT_FORMAT and doc["digest"]
    row = next(i for i in doc["items"] if i["title"] == "Egg collection leaflet")
    assert row["status"] == "approved" and row["approved_sha256"] and "embedding" not in row
    cfg = copy.deepcopy(env["cfg"]); cfg["routing"]["default"]["embeddings"] = ["local:local-hash-1536"]
    registry.set_config(cfg)
    monkeypatch.setattr(content, "_try_embed", knowledge._try_embed)
    res = hub.reindex(db, env["world"]["a"])
    assert res["active_model"] == "local:local-hash-1536" and res["reembedded"] >= 1 and res["failed"] == 0
    item = (db.query(CareContentItem).filter_by(title="Egg collection leaflet", status="approved")
            .order_by(CareContentItem.created_at.desc()).first())
    chunks = db.query(CareContentChunk).filter_by(item_id=item.id).all()
    assert chunks and all(ch.embedding_model == "local:local-hash-1536" and ch.embedding is not None for ch in chunks)
    assert hub.reindex(db, env["world"]["a"])["candidates"] == 0  # idempotent
