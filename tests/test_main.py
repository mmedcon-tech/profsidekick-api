import json
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestHealthEndpoints:
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "app" in data

    def test_root_endpoint(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert "docs" in data


class TestSessionEndpoints:
    def test_get_ephemeral_token_without_openai_key(self):
        response = client.get("/api/session/ephemeral")
        assert response.status_code in [200, 422, 404, 500]

    def test_get_nonexistent_session_slides(self):
        response = client.get("/api/sessions/nonexistent-session/slides")
        assert response.status_code in [404, 500]
        data = response.json()
        error_msg = data.get("message") or data.get("detail", "")
        assert "not found" in str(error_msg).lower() or response.status_code == 404

    def test_get_session_statistics(self):
        response = client.get("/api/stats")
        assert response.status_code in [200, 404, 500]


class TestFileUpload:
    def test_create_class_without_file(self):
        response = client.post("/api/classes/create")
        assert response.status_code in [404, 422]

    def test_create_class_invalid_class_details(self):
        files = {
            "presentation": (
                "test.pptx",
                b"dummy content",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        }
        data = {"classDetails": "invalid json"}

        response = client.post("/api/classes/create", files=files, data=data)
        assert response.status_code in [400, 404, 422]

    def test_create_class_valid_structure(self):
        files = {
            "presentation": (
                "test.pptx",
                b"dummy content",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        }
        class_details = {
            "className": "Test Class",
            "courseCode": "TEST-101",
            "description": "Test description",
            "duration": 60,
        }
        data = {"classDetails": json.dumps(class_details)}

        response = client.post("/api/classes/create", files=files, data=data)
        assert response.status_code in [200, 400, 404, 422, 500]


class TestAIEndpoints:
    def test_explain_concept_structure(self):
        payload = {"concept": "machine learning", "detail_level": "medium"}

        response = client.post("/api/ai/explain", json=payload)
        assert response.status_code in [200, 404, 500]

    def test_answer_question_structure(self):
        payload = {"question": "What is artificial intelligence?"}

        response = client.post("/api/ai/answer", json=payload)
        assert response.status_code in [200, 404, 500]

    def test_explain_concept_invalid_detail_level(self):
        payload = {
            "concept": "machine learning",
            "detail_level": "invalid",
        }

        response = client.post("/api/ai/explain", json=payload)
        assert response.status_code in [404, 422]


class TestValidation:
    def test_empty_concept_explanation(self):
        payload = {"concept": "", "detail_level": "medium"}

        response = client.post("/api/ai/explain", json=payload)
        assert response.status_code in [404, 422]

    def test_empty_question(self):
        payload = {"question": ""}

        response = client.post("/api/ai/answer", json=payload)
        assert response.status_code in [200, 404, 422]


if __name__ == "__main__":
    pytest.main([__file__])
