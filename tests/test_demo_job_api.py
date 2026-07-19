import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

import bag_doctor.main as main
from bag_doctor.investigator import MODEL, investigate
from bag_doctor.jobs import _jobs, _lock, get_job


class FakeResponses:
    def __init__(self, evidence_id):
        self.evidence_id = evidence_id
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            call = SimpleNamespace(
                type="function_call", name="list_evidence", call_id="demo-call",
                arguments=json.dumps({"offset": 0, "limit": 5, "topic": None, "evidence_type": None}),
            )
            return SimpleNamespace(output=[call], output_text="")
        payload = {
            "model": MODEL, "question": "q", "summary": "A bounded timing gap was observed.",
            "observations": [],
            "hypotheses": [{"rank": 1, "hypothesis": "Possible scheduling delay", "confidence": "low", "reasoning": "Timing evidence only", "evidence_ids": [self.evidence_id]}],
            "limitations": ["Timing measurements alone do not establish a physical root cause."],
            "tool_trace": [],
        }
        return SimpleNamespace(output=[], output_text=json.dumps(payload))


class FakeClient:
    def __init__(self, evidence_id):
        self.responses = FakeResponses(evidence_id)


def test_demo_job_is_completed_retrievable_and_has_bounded_evidence():
    route = next(route for route in main.app.routes if isinstance(route, APIRoute) and route.path == "/api/analyze/demo/job")
    assert "GET" in route.methods

    created = main.analyze_demo_job()
    assert created["job_id"]
    assert created["state"] == "completed"
    assert created["has_result"] is True
    assert "result" not in created
    assert "path" not in created

    fetched = main.job_status(created["job_id"])
    assert fetched["state"] == "completed"
    assert fetched["result"]["summary"]["storage_format"] == "mcap"
    assert fetched["result"]["summary"]["topic_count"] == 3

    evidence = main.job_evidence(created["job_id"], limit=50, offset=0)
    assert evidence["total_count"] >= evidence["returned_count"] > 0
    item = main.job_evidence_item(created["job_id"], evidence["items"][0]["evidence_id"])
    assert item["evidence_id"] == evidence["items"][0]["evidence_id"]


def test_demo_job_supports_investigation_without_upload_or_local_job():
    created = main.analyze_demo_job()
    evidence = main.job_evidence(created["job_id"], limit=50, offset=0)["items"]
    result = investigate(created["job_id"], "q", client=FakeClient(evidence[0]["evidence_id"]))
    assert result.model == MODEL
    assert result.hypotheses[0].evidence_ids == [evidence[0]["evidence_id"]]
    assert "physical root cause" in result.limitations[0]


def test_repeated_demo_jobs_are_independently_registered():
    first = main.analyze_demo_job()
    second = main.analyze_demo_job()
    assert first["job_id"] != second["job_id"]
    assert get_job(first["job_id"]).result is not get_job(second["job_id"]).result
    assert get_job(first["job_id"]).state == get_job(second["job_id"]).state == "completed"


def test_demo_failure_is_sanitized_and_does_not_register_job(monkeypatch):
    with _lock:
        before = set(_jobs)
    monkeypatch.setattr(main, "analyze_bag", lambda _path: (_ for _ in ()).throw(RuntimeError("secret path /private token stderr")))
    with pytest.raises(HTTPException) as caught:
        main.analyze_demo_job()
    assert caught.value.status_code == 500
    assert caught.value.detail == "Demo analysis could not be completed"
    with _lock:
        assert set(_jobs) == before


def test_direct_demo_endpoint_remains_compatible_and_does_not_register_job():
    with _lock:
        before = set(_jobs)
    result = main.analyze_demo()
    assert result.summary.storage_format == "mcap"
    assert result.summary.topic_count == 3
    assert result.incidents[0].topic == "/scan"
    with _lock:
        assert set(_jobs) == before
