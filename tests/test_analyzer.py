from pathlib import Path

import pytest

from bag_doctor.analyzer import analyze_bag
from bag_doctor.main import DEMO_BAG


@pytest.fixture(scope="module")
def analysis():
    assert Path(DEMO_BAG).exists(), "Bundled demo bag must be generated"
    return analyze_bag(DEMO_BAG)


def test_demo_inventory_and_rates(analysis):
    topics = {topic.topic: topic for topic in analysis.topics}
    assert set(topics) == {"/scan", "/odom", "/tf"}
    assert analysis.summary.duration_seconds == pytest.approx(14.0)
    assert topics["/scan"].median_rate_hz == pytest.approx(10.0)
    assert topics["/odom"].median_rate_hz == pytest.approx(30.0)


def test_scan_silence_is_detected(analysis):
    scan_incidents = [incident for incident in analysis.incidents if incident.topic == "/scan"]
    assert len(scan_incidents) == 1
    incident = scan_incidents[0]
    assert incident.start_seconds == pytest.approx(4.9, abs=0.11)
    assert incident.end_seconds == pytest.approx(9.0, abs=0.01)
    assert incident.duration_seconds == pytest.approx(4.1, abs=0.01)


def test_healthy_topics_have_no_silence(analysis):
    topics = {topic.topic: topic for topic in analysis.topics}
    assert topics["/odom"].silence_windows == []
    assert topics["/tf"].silence_windows == []

