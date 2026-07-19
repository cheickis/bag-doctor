from dataclasses import dataclass

import pytest
from pydantic import ValidationError

import bag_doctor.analyzer as analyzer
from bag_doctor.classification import TopicTimingConfiguration


@dataclass
class Source:
    records: list[tuple[str, int]]
    storage_format: str = "synthetic"
    topic_types: dict[str, str] = None
    total_messages: int | None = None

    def __post_init__(self):
        self.topic_types = self.topic_types or {topic: "test/Msg" for topic, _ in self.records}
        self.total_messages = len(self.records)

    def messages(self):
        for topic, timestamp in self.records:
            yield type("Record", (), {"topic": topic, "timestamp_ns": timestamp})()

    def close(self):
        pass


def run(monkeypatch, records, config=None):
    source = Source(records)
    monkeypatch.setattr(analyzer, "open_bag_source", lambda _: source)
    return analyzer.analyze_bag("synthetic", topic_configuration=config)


def test_stable_periodic_topic_is_classified(monkeypatch):
    result = run(monkeypatch, [("/camera", i * 100_000_000) for i in range(40)])
    assert result.topics[0].timing_classification == "periodic"


def test_sparse_irregular_topic_is_unknown(monkeypatch):
    result = run(monkeypatch, [("/sparse", 0), ("/sparse", 5_000_000_000), ("/sparse", 20_000_000_000)])
    assert result.topics[0].timing_classification == "unknown"
    assert result.topics[0].silence_windows == []


def test_rosout_is_event_driven_and_not_silence_checked(monkeypatch):
    result = run(monkeypatch, [("/rosout", i * 100_000_000) for i in range(30)] + [("/rosout", 10_000_000_000)])
    topic = result.topics[0]
    assert topic.timing_classification == "event_driven"
    assert topic.silence_window_count == 0
    assert result.incidents == []


def test_user_configuration_overrides_rosout_and_threshold(monkeypatch):
    config = TopicTimingConfiguration(topics={"/rosout": {"expected_rate_hz": 10, "gap_threshold_seconds": 2}})
    records = [("/rosout", i * 100_000_000) for i in range(30)] + [("/rosout", 5_000_000_000)]
    result = run(monkeypatch, records, config)
    topic = result.topics[0]
    assert topic.timing_classification == "user_configured"
    assert topic.silence_window_count == 1


def test_invalid_timing_configuration_is_rejected():
    with pytest.raises(ValidationError):
        TopicTimingConfiguration(topics={"/x": {"expected_rate_hz": 0}})
    with pytest.raises(ValidationError):
        TopicTimingConfiguration(topics={"/x": {"classification": "event_driven", "gap_threshold_seconds": 1}})


def test_configured_gap_threshold_changes_detection(monkeypatch):
    records = [("/x", i * 100_000_000) for i in range(30)] + [("/x", 8_000_000_000)]
    low = TopicTimingConfiguration(topics={"/x": {"expected_rate_hz": 10, "gap_threshold_seconds": 1}})
    high = TopicTimingConfiguration(topics={"/x": {"expected_rate_hz": 10, "gap_threshold_seconds": 6}})
    assert run(monkeypatch, records, low).topics[0].silence_window_count == 1
    assert run(monkeypatch, records, high).topics[0].silence_window_count == 0
