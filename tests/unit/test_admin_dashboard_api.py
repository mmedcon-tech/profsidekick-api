from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database.connection import get_db
from app.dependencies.auth import require_admin, require_publisher
from app.api.admin import analytics_api
from app.main import app
from app.services import model_catalog_service


@pytest.fixture
def client():
    def override_db():
        yield object()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_publisher] = lambda: None
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _model(**overrides):
    model_url = "https://cdn.example.com/avatar.glb"
    thumbnail_url = "https://cdn.example.com/avatar.png"
    values = {
        "id": uuid4(),
        "name": "Sample avatar",
        "description": None,
        "model_type": "three_js",
        "model_url": model_url,
        "thumbnail_url": thumbnail_url,
        "file_path": model_url,
        "preview_image_path": thumbnail_url,
        "gender": "neutral",
        "supported_languages": ["en"],
        "sort_order": 0,
        "is_active": True,
        "created_at": datetime(2025, 1, 1),
    }
    values.update(overrides)
    return values


def test_admin_analytics_route_returns_dashboard_contract(client, monkeypatch):
    payload = {
        "total_users": 3,
        "total_publishers": 1,
        "total_subscribers": 2,
        "total_programs": 0,
        "total_courses": 1,
        "total_avatars": 1,
        "total_session_runs": 2,
        "total_credits_consumed": 0,
        "system_health": 100,
        "active_sessions_today": 0,
        "monthly_completions": [{"month": "Jan 2025", "value": 1}],
        "course_performance": [{"name": "Course", "completion": 50, "subscribers": 2}],
        "at_risk_learners": [],
    }
    monkeypatch.setattr(
        analytics_api, "get_admin_analytics", lambda db: payload
    )

    response = client.get("/api/admin/analytics")

    assert response.status_code == 200
    assert response.json() == payload


def test_admin_model_catalog_lists_compatibility_fields(client, monkeypatch):
    monkeypatch.setattr(
        model_catalog_service, "list_models", lambda db, active_only=False: [_model()]
    )

    response = client.get("/api/admin/3d-models")

    assert response.status_code == 200
    model = response.json()["models"][0]
    assert model["model_url"] == model["file_path"]
    assert model["thumbnail_url"] == model["preview_image_path"]


def test_publisher_catalog_returns_only_active_models(client, monkeypatch):
    observed = {}

    def list_models(db, active_only=False):
        observed["active_only"] = active_only
        return [_model()]

    monkeypatch.setattr(model_catalog_service, "list_models", list_models)

    response = client.get("/api/publisher/3d-models")

    assert response.status_code == 200
    assert observed["active_only"] is True


def test_admin_can_create_a_model(client, monkeypatch):
    created = _model()
    monkeypatch.setattr(
        model_catalog_service, "create_model", lambda db, payload: created
    )

    response = client.post(
        "/api/admin/3d-models",
        json={
            "name": "Sample avatar",
            "model_type": "three_js",
            "model_url": "https://cdn.example.com/avatar.glb",
            "gender": "neutral",
            "supported_languages": ["en"],
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(created["id"])


def test_admin_model_update_returns_404_for_unknown_id(client, monkeypatch):
    monkeypatch.setattr(
        model_catalog_service, "update_model", lambda db, model_id, payload: None
    )

    response = client.patch(
        f"/api/admin/3d-models/{uuid4()}",
        json={"is_active": False},
    )

    assert response.status_code == 404
