"""Smoke test verifying the API app and endpoints targeted by Dockerfile."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.api.app import app
from src.api.recommendations import clear_model_cache


def test_dockerfile_exists_and_configured():
    """Verify Dockerfile and .dockerignore exist and specify correct entrypoint."""
    dockerfile_path = Path("Dockerfile")
    dockerignore_path = Path(".dockerignore")

    assert dockerfile_path.exists(), "Dockerfile must exist at project root"
    assert dockerignore_path.exists(), ".dockerignore must exist at project root"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "python:3.11-slim" in content
    assert "EXPOSE 8000" in content
    assert "src.api.app:app" in content
    assert "0.0.0.0" in content
    assert "8000" in content

    ignore_content = dockerignore_path.read_text(encoding="utf-8")
    assert "data/" in ignore_content
    assert "models/" in ignore_content
    assert "tests/" in ignore_content
    assert ".venv/" in ignore_content


def test_api_health_and_root_endpoints():
    """Verify health and root endpoints respond as expected by container healthcheck."""
    client = TestClient(app)

    # Health check endpoint (used by Docker HEALTHCHECK)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Root API endpoint
    api_resp = client.get("/api")
    assert api_resp.status_code == 200
    assert "Recommendations API" in api_resp.text

    # Web UI root endpoint
    ui_resp = client.get("/")
    assert ui_resp.status_code == 200


def test_api_recommendations_smoke():
    """Verify recommendations endpoint responds with local storage backend."""
    client = TestClient(app)
    clear_model_cache()

    # Query telco_default recommendations
    response = client.get(
        "/recommendations",
        params={"customer_id": "7590-VHVEG", "top_n": 5},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "telco_default"
    assert len(data["recommendations"]) == 5
