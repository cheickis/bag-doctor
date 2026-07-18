from fastapi.testclient import TestClient

from bag_doctor.main import app


def test_demo_analysis_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/analyze/demo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["storage_format"] == "mcap"
    assert payload["summary"]["topic_count"] == 3
    assert payload["incidents"][0]["topic"] == "/scan"


def test_browser_page():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Analyze Failed Robot Demo" in response.text
