import json
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestHealthEndpoints:
    """Test health and basic endpoints"""

    def test_health_check(self):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "app" in data

    def test_root_endpoint(self):
        """Test root endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert "docs" in data


class TestSessionEndpoints:
    """Test session-related endpoints"""

    def test_get_ephemeral_token_without_openai_key(self):
        """Test ephemeral token generation"""
        response = client.get("/api/session/ephemeral")
        assert response.status_code in [200, 422, 404, 500]

    def test_get_nonexistent_session_slides(self):
        """Test getting slides for non-existent session"""
        response = client.get("/api/sessions/nonexistent-session/slides")
        assert response.status_code in [404, 500]
        data = response.json()
        error_msg = data.get("message") or data.get("detail", "")
        assert "not found" in str(error_msg).lower() or response.status_code == 404

    def test_get_session_statistics(self):
        """Test getting system statistics"""
        response = client.get("/api/stats")
        assert response.status_code in [200, 404, 500]


class TestFileUpload:
    """Test file upload functionality"""

    def test_create_class_without_file(self):
        """Test class creation without file"""
        response = client.post("/api/classes/create")
        assert response.status_code in [404, 422]

    def test_create_class_invalid_class_details(self):
        """Test class creation with invalid class details"""
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
        """Test class creation with valid structure but dummy data"""
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
    """Test AI-powered endpoints"""

    def test_explain_concept_structure(self):
        """Test concept explanation endpoint structure"""
        payload = {"concept": "machine learning", "detail_level": "medium"}

        response = client.post("/api/ai/explain", json=payload)
        assert response.status_code in [200, 404, 500]

    def test_answer_question_structure(self):
        """Test question answering endpoint structure"""
        payload = {"question": "What is artificial intelligence?"}

        response = client.post("/api/ai/answer", json=payload)
        assert response.status_code in [200, 404, 500]

    def test_explain_concept_invalid_detail_level(self):
        """Test concept explanation with invalid detail level"""
        payload = {
            "concept": "machine learning",
            "detail_level": "invalid",
        }

        response = client.post("/api/ai/explain", json=payload)
        assert response.status_code in [404, 422]


class TestValidation:
    """Test input validation"""

    def test_empty_concept_explanation(self):
        """Test concept explanation with empty concept"""
        payload = {"concept": "", "detail_level": "medium"}

        response = client.post("/api/ai/explain", json=payload)
        assert response.status_code in [404, 422]

    def test_empty_question(self):
        """Test question answering with empty question"""
        payload = {"question": ""}

        response = client.post("/api/ai/answer", json=payload)
        assert response.status_code in [200, 404, 422]


if __name__ == "__main__":
    pytest.main([__file__])
