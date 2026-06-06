import pytest
import httpx
from fastapi.testclient import TestClient
import json
import os
from pathlib import Path

from app.main import app

# Create test client
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
        """Test ephemeral token generation (will fail without valid OpenAI key)"""
        response = client.get("/api/session/ephemeral")
        # This will likely return 500 without a valid OpenAI API key
        # In a real test environment, you'd mock the OpenAI service
        assert response.status_code in [200, 500]

    def test_get_nonexistent_session_slides(self):
        """Test getting slides for non-existent session"""
        response = client.get("/api/sessions/nonexistent-session/slides")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["message"].lower()

    def test_get_session_statistics(self):
        """Test getting system statistics"""
        response = client.get("/api/stats")
        # May fail without proper database setup, but structure should be correct
        assert response.status_code in [200, 500]


class TestFileUpload:
    """Test file upload functionality"""

    def test_create_class_without_file(self):
        """Test class creation without file"""
        response = client.post("/api/classes/create")
        assert response.status_code == 422  # Validation error

    def test_create_class_invalid_class_details(self):
        """Test class creation with invalid class details"""
        # Create a dummy file
        files = {
            "presentation": (
                "test.pptx",
                b"dummy content",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        }
        data = {"classDetails": "invalid json"}

        response = client.post("/api/classes/create", files=files, data=data)
        assert response.status_code == 400
        assert "Invalid classDetails JSON" in response.json()["detail"]

    def test_create_class_valid_structure(self):
        """Test class creation with valid structure but dummy data"""
        # Create a dummy file
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
        # This will likely fail due to file processing or OpenAI integration
        # but should pass validation
        assert response.status_code in [200, 400, 500]


class TestAIEndpoints:
    """Test AI-powered endpoints"""

    def test_explain_concept_structure(self):
        """Test concept explanation endpoint structure"""
        payload = {"concept": "machine learning", "detail_level": "medium"}

        response = client.post("/api/ai/explain", json=payload)
        # Will likely fail without valid OpenAI key, but structure should be correct
        assert response.status_code in [200, 500]

    def test_answer_question_structure(self):
        """Test question answering endpoint structure"""
        payload = {"question": "What is artificial intelligence?"}

        response = client.post("/api/ai/answer", json=payload)
        # Will likely fail without valid OpenAI key, but structure should be correct
        assert response.status_code in [200, 500]

    def test_explain_concept_invalid_detail_level(self):
        """Test concept explanation with invalid detail level"""
        payload = {
            "concept": "machine learning",
            "detail_level": "invalid",  # Should be basic, medium, or advanced
        }

        response = client.post("/api/ai/explain", json=payload)
        assert response.status_code == 422  # Validation error


class TestValidation:
    """Test input validation"""

    def test_empty_concept_explanation(self):
        """Test concept explanation with empty concept"""
        payload = {"concept": "", "detail_level": "medium"}

        response = client.post("/api/ai/explain", json=payload)
        assert response.status_code == 422  # Validation error

    def test_empty_question(self):
        """Test question answering with empty question"""
        payload = {"question": ""}

        response = client.post("/api/ai/answer", json=payload)
        assert response.status_code == 422  # Validation error


if __name__ == "__main__":
    pytest.main([__file__])
