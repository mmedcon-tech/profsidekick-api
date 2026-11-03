from app.services.care import health
from tests.test_care_platform import _as, _user, stub_ai, world  # noqa: F401


def test_demo_is_open_but_never_real_data(monkeypatch, client):
    monkeypatch.delenv("MYOS_ENVIRONMENT", raising=False)
    g = health.real_data_gate()
    assert g["open"] and g["real_patient_data"] is False


def test_production_without_signoff_closes_patient_routes(monkeypatch, client):
    monkeypatch.setenv("MYOS_ENVIRONMENT", "production")
    monkeypatch.delenv("MYOS_REAL_DATA_SIGNOFF", raising=False)
    g = health.real_data_gate()
    assert not g["open"] and "signoff_missing" in g["blockers"]
    r = client.get("/api/care/agent/v1/preferences")
    assert r.status_code == 503 and r.json()["error"] == "real_patient_data_gate"
    assert client.get("/api/care/c/any/memory").status_code == 503


def test_signoff_alone_is_not_enough_without_phi_cleared_provider(monkeypatch, client):
    monkeypatch.setenv("MYOS_ENVIRONMENT", "production")
    monkeypatch.setenv("MYOS_REAL_DATA_SIGNOFF", "ticket-123")
    assert "no_provider_cleared_for_phi" in health.real_data_gate()["blockers"]
