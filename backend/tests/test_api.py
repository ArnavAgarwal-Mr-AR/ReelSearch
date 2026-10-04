import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestApiEndpoints:
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_save_reel_invalid_host(self):
        response = client.post("/api/v1/reels", json={"url": "https://evil.com/reel/123/"})
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "INVALID_HOST"

    def test_save_reel_non_reel_path(self):
        response = client.post("/api/v1/reels", json={"url": "https://www.instagram.com/p/123/"})
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "INVALID_REEL_PATH"

    def test_search_query_too_short(self):
        response = client.get("/api/v1/search?q=a")
        # FastAPI Query min_length returns 422 or our custom check returns 400
        assert response.status_code in {400, 422}

    def test_save_and_retrieve_flow(self):
        # Valid Reel URL
        valid_url = "https://www.instagram.com/reel/CtestApiFlow99/?utm_source=test"
        res = client.post("/api/v1/reels", json={"url": valid_url})
        assert res.status_code in {200, 202}
        reel_data = res.json()
        assert reel_data["canonical_url"] == "https://www.instagram.com/reel/CtestApiFlow99/"
        assert "reel_id" in reel_data

        # Check status endpoint
        reel_id = reel_data["reel_id"]
        status_res = client.get(f"/api/v1/reels/{reel_id}")
        assert status_res.status_code == 200
        assert status_res.json()["reel_id"] == reel_id

    def test_validation_error_envelope(self):
        # Sending missing 'url' payload to verify global validation exception handler
        response = client.post("/api/v1/reels", json={})
        assert response.status_code == 422
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "details" in data["error"]

    def test_not_found_error_envelope(self):
        response = client.get("/api/v1/reels/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "REEL_NOT_FOUND"
