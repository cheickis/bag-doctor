import re
import time

import pytest
from fastapi.testclient import TestClient

from bag_doctor.main import DEMO_BAG, FRONTEND_INDEX, app, job_payload
from bag_doctor.jobs import create_job, request_cancel, get_job, Job, _jobs, _lock
from bag_doctor.analyzer import AnalysisCancelled, AnalysisProgress, analyze_bag
from bag_doctor.jobs import _update_progress


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
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == FRONTEND_INDEX.read_text()
    assert '<div id="root"></div>' in response.text
    assert re.search(r'<script[^>]+src="/assets/index-[^"]+\.js"', response.text)
    assert re.search(r'<link[^>]+href="/assets/index-[^"]+\.css"', response.text)


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


def test_cancel_job_reaches_terminal_cancelled():
    job = create_job(DEMO_BAG)
    request_cancel(job.id)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and get_job(job.id).state not in {"cancelled", "completed", "error"}:
        time.sleep(0.01)
    assert get_job(job.id).state == "cancelled"
    assert get_job(job.id).result is None
    assert get_job(job.id).error is None
    assert request_cancel(job.id).state == "cancelled"


def test_analyzer_cancellation_callback_raises():
    with pytest.raises(AnalysisCancelled):
        analyze_bag(DEMO_BAG, cancel_requested=lambda: True)


def test_analyzer_progress_initial_final_and_monotonic():
    updates = []
    result = analyze_bag(DEMO_BAG, progress_callback=updates.append)
    assert updates[0] == AnalysisProgress(0, result.summary.total_messages)
    assert updates[-1] == AnalysisProgress(result.summary.total_messages, result.summary.total_messages)
    assert [item.processed_messages for item in updates] == sorted(item.processed_messages for item in updates)


def test_job_progress_percentage_and_eta_rules():
    job = create_job(DEMO_BAG)
    _update_progress(job, AnalysisProgress(10, 100))
    assert 0 < job.percent < 100
    assert job.eta_seconds is not None
    _update_progress(job, AnalysisProgress(10, None))
    assert job.percent is None
    assert job.eta_seconds is None


def test_unknown_progress_total_remains_truthful_in_job_payload():
    job = Job("unknown-total", DEMO_BAG, state="running")
    _update_progress(job, AnalysisProgress(processed_messages=8, total_messages=None))

    payload = job_payload(job, include_result=False)
    assert payload["processed_messages"] == 8
    assert payload["total_messages"] is None
    assert payload["percent_complete"] is None
    assert payload["estimated_remaining_seconds"] is None


def test_sse_cancelled_and_job_error_events_close():
    cancelled = Job("cancelled-sse", DEMO_BAG, state="cancelled")
    failed = Job("error-sse", DEMO_BAG, state="error", error="synthetic failure")
    with _lock:
        _jobs[cancelled.id] = cancelled
        _jobs[failed.id] = failed
    with TestClient(app) as client:
        with client.stream("GET", f"/api/analyze/jobs/{cancelled.id}/events") as stream:
            cancelled_body = "".join(stream.iter_text())
        with client.stream("GET", f"/api/analyze/jobs/{failed.id}/events") as stream:
            failed_body = "".join(stream.iter_text())
    assert "event: cancelled" in cancelled_body
    assert "event: job-error" in failed_body
    assert "event: error\n" not in failed_body
