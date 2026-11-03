import asyncio
from types import SimpleNamespace

from app.services.ai import registry
from app.services.care import health

CLINIC = SimpleNamespace(slug="demo", is_demo=True)


def _run(monkeypatch, result):
    async def fake(live=True, request_id=None):
        return result
    monkeypatch.setattr(health, "check_tts", fake)
    health._TTS_CACHE.update(at=0.0, result=None)
    return asyncio.run(health.voice_available(CLINIC))


def test_voice_available_when_configured_eligible_and_in_quota(monkeypatch):
    assert _run(monkeypatch, {"ok": True, "error_kind": None})["available"] is True


def test_voice_hidden_when_out_of_quota_or_unconfigured(monkeypatch):
    assert _run(monkeypatch, {"ok": False, "error_kind": "quota"}) == {"available": False, "reason": "quota"}
    assert _run(monkeypatch, {"ok": False, "error_kind": "config"})["reason"] == "config"


def test_voice_hidden_when_not_eligible_for_clinic_data(monkeypatch):
    monkeypatch.setattr(registry, "clinic_data_class", lambda cfg, c: "phi")
    r = _run(monkeypatch, {"ok": True, "error_kind": None})
    assert r["available"] is False and r["reason"] == "data_class_not_permitted"
