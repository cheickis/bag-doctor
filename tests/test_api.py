from fastapi.testclient import TestClient

from bag_doctor.main import app
from bag_doctor.jobs import create_job
from bag_doctor.main import DEMO_BAG
import time, json


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
    assert "Open Local Bag" in response.text
    assert "/api/analyze/local" in response.text
    assert "EventSource" in response.text
    assert "Upload Small Bag" in response.text


def test_job_endpoint_and_sse_exclude_result():
    job = create_job(DEMO_BAG)
    with TestClient(app) as client:
        with client.stream("GET", f"/api/analyze/jobs/{job.id}/events") as stream:
            body = "".join(stream.iter_text())
        full = client.get(f"/api/analyze/jobs/{job.id}")
    assert "event: completed" in body
    assert '"result"' not in body
    assert full.status_code == 200
    assert full.json()["result"]["summary"]["topic_count"] == 3


def test_unknown_job_is_404():
    with TestClient(app) as client:
        assert client.get("/api/analyze/jobs/missing/events").status_code == 404
        assert client.get("/api/analyze/jobs/missing").status_code == 404
