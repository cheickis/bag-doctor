from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import bag_doctor.analyzer as analyzer
import bag_doctor.main as main
from bag_doctor.analysis_workspace import AnalysisWorkspace
from bag_doctor.analyzer import AnalysisLimits, analyze_bag
from bag_doctor.classification import TopicTimingConfiguration
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


@dataclass
class SyntheticSource:
    records: list[tuple[str, int]]

    storage_format = "synthetic"

    def __post_init__(self):
        self.records.sort(key=lambda item: (item[1], item[0]))
        self.topic_types = {topic: "test/Msg" for topic, _ in self.records}
        self.total_messages = len(self.records)

    def messages(self):
        for topic, timestamp in self.records:
            yield SimpleNamespace(topic=topic, timestamp_ns=timestamp)

    def close(self):
        pass


def synthetic_analysis(monkeypatch, tmp_path, records, **kwargs):
    source = SyntheticSource(records)
    monkeypatch.setattr(analyzer, "open_bag_source", lambda _path: source)
    return analyze_bag(tmp_path / "synthetic", **kwargs)


def periodic_records(topic, start_tenths, end_tenths):
    return [(topic, index * 100_000_000) for index in range(start_tenths, end_tenths + 1)]


def test_trailing_boundary_silence_preserves_statistics_and_evidence(monkeypatch, tmp_path):
    records = periodic_records("/periodic", 0, 79) + [("/recording_end", 13_900_000_000)]
    result = synthetic_analysis(monkeypatch, tmp_path, records)
    topic = next(item for item in result.topics if item.topic == "/periodic")

    assert topic.timing_classification == "periodic"
    assert topic.median_rate_hz == pytest.approx(10.0)
    assert topic.maximum_gap_seconds == pytest.approx(0.1)
    assert topic.silence_window_count == 1
    trailing = topic.silence_windows[0]
    assert (trailing.start_seconds, trailing.end_seconds, trailing.duration_seconds) == pytest.approx((7.9, 13.9, 6.0))
    assert trailing.expected_period_seconds == pytest.approx(0.1)
    assert result.incidents[0].evidence_id == trailing.evidence_id

    job = SimpleNamespace(result=result)
    monkeypatch.setattr(main, "get_job", lambda _job_id: job)
    evidence = main.job_evidence("synthetic", limit=50, offset=0)
    assert evidence["items"][0]["evidence_id"] == trailing.evidence_id
    assert main.job_evidence_item("synthetic", trailing.evidence_id)["evidence_id"] == trailing.evidence_id

    repeated = synthetic_analysis(monkeypatch, tmp_path, records)
    assert [item.evidence_id for item in repeated.incidents] == [item.evidence_id for item in result.incidents]


def test_leading_boundary_silence_preserves_statistics(monkeypatch, tmp_path):
    records = [("/recording_start", 0)] + periodic_records("/periodic", 60, 99)
    result = synthetic_analysis(monkeypatch, tmp_path, records)
    topic = next(item for item in result.topics if item.topic == "/periodic")

    assert topic.timing_classification == "periodic"
    assert topic.median_rate_hz == pytest.approx(10.0)
    assert topic.maximum_gap_seconds == pytest.approx(0.1)
    assert topic.silence_window_count == 1
    leading = topic.silence_windows[0]
    assert (leading.start_seconds, leading.end_seconds, leading.duration_seconds) == pytest.approx((0.0, 6.0, 6.0))


def test_boundary_threshold_equality_and_configured_precedence(monkeypatch, tmp_path):
    config = TopicTimingConfiguration(topics={"/configured": {"expected_rate_hz": 10, "gap_threshold_seconds": 1}})
    below = [("/bounds", 0), ("/bounds", 3_900_000_000)] + periodic_records("/configured", 9, 30)
    below_result = synthetic_analysis(monkeypatch, tmp_path, below, topic_configuration=config)
    assert next(item for item in below_result.topics if item.topic == "/configured").silence_window_count == 0

    equal = [("/bounds", 0), ("/bounds", 3_900_000_000)] + periodic_records("/configured", 10, 29)
    equal_result = synthetic_analysis(monkeypatch, tmp_path, equal, topic_configuration=config)
    equal_topic = next(item for item in equal_result.topics if item.topic == "/configured")
    assert equal_topic.timing_classification == "user_configured"
    assert [window.duration_seconds for window in equal_topic.silence_windows] == [1.0, 1.0]

    high = TopicTimingConfiguration(topics={"/configured": {"expected_rate_hz": 10, "gap_threshold_seconds": 1.1}})
    high_result = synthetic_analysis(monkeypatch, tmp_path, equal, topic_configuration=high)
    assert next(item for item in high_result.topics if item.topic == "/configured").silence_window_count == 0

    internal_and_boundary = [("/bounds", 0), ("/bounds", 4_900_000_000)] + periodic_records("/configured", 10, 20) + periodic_records("/configured", 30, 39)
    combined = synthetic_analysis(monkeypatch, tmp_path, internal_and_boundary, topic_configuration=config)
    configured = next(item for item in combined.topics if item.topic == "/configured")
    assert configured.silence_window_count == 3
    assert [window.duration_seconds for window in configured.silence_windows] == [1.0, 1.0, 1.0]


def test_boundary_silence_respects_classification_eligibility(monkeypatch, tmp_path):
    records = [("/bounds", 0), ("/bounds", 10_000_000_000)]
    records += periodic_records("/rosout", 20, 49)
    records += periodic_records("/parameter_events", 20, 49)
    records += [("/unknown", 2_000_000_000), ("/unknown", 4_000_000_000)]
    records += periodic_records("/configured", 20, 49)
    config = TopicTimingConfiguration(topics={"/configured": {"expected_rate_hz": 10, "gap_threshold_seconds": 1}})
    result = synthetic_analysis(monkeypatch, tmp_path, records, topic_configuration=config)
    topics = {topic.topic: topic for topic in result.topics}

    assert topics["/rosout"].timing_classification == "event_driven"
    assert topics["/parameter_events"].timing_classification == "event_driven"
    assert topics["/unknown"].timing_classification == "unknown"
    assert all(topics[name].silence_window_count == 0 for name in ("/rosout", "/parameter_events", "/unknown"))
    assert topics["/configured"].timing_classification == "user_configured"
    assert topics["/configured"].silence_window_count == 2


def test_combined_boundary_internal_bounding_order_and_cleanup(monkeypatch, tmp_path):
    class CapturingWorkspace(AnalysisWorkspace):
        instance = None

        def __init__(self, batch_size):
            super().__init__(batch_size)
            CapturingWorkspace.instance = self

    records = [("/bounds", 0), ("/bounds", 13_900_000_000)]
    records += periodic_records("/periodic", 20, 49) + periodic_records("/periodic", 80, 109)
    limits = AnalysisLimits(max_silence_windows_per_topic=2, max_incidents=2)
    result = synthetic_analysis(monkeypatch, tmp_path, records, limits=limits, workspace_factory=CapturingWorkspace)
    topic = next(item for item in result.topics if item.topic == "/periodic")

    assert topic.silence_window_count == result.incident_count == 3
    assert topic.returned_silence_window_count == result.returned_incident_count == 2
    assert topic.silence_windows_truncated and result.incidents_truncated
    assert [(item.duration_seconds, item.start_seconds) for item in result.incidents] == [(3.1, 4.9), (3.0, 10.9)]
    assert [item.evidence_id for item in topic.silence_windows] == [item.evidence_id for item in result.incidents]
    assert CapturingWorkspace.instance is not None and not CapturingWorkspace.instance.path.exists()

    repeated = synthetic_analysis(monkeypatch, tmp_path, records, limits=limits)
    assert [item.evidence_id for item in repeated.incidents] == [item.evidence_id for item in result.incidents]
    assert [(item.duration_seconds, item.start_seconds) for item in repeated.incidents] == [(3.1, 4.9), (3.0, 10.9)]

    zero = synthetic_analysis(
        monkeypatch, tmp_path, records,
        limits=AnalysisLimits(max_silence_windows_per_topic=0, max_incidents=0),
    )
    zero_topic = next(item for item in zero.topics if item.topic == "/periodic")
    assert zero_topic.silence_window_count == zero.incident_count == 3
    assert zero_topic.silence_windows == zero.incidents == []
    assert zero_topic.silence_windows_truncated and zero.incidents_truncated
