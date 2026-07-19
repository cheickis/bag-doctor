from pathlib import Path
from dataclasses import dataclass
import json
import sqlite3
import tracemalloc

import pytest
from fastapi.encoders import jsonable_encoder

import bag_doctor.analyzer as analyzer
from bag_doctor.analyzer import AnalysisCancelled, AnalysisLimits, analyze_bag
from bag_doctor.ingestion.reader import TimestampRecord


@dataclass
class SyntheticSource:
    storage_format: str = "synthetic"
    total_messages: int | None = None
    topic_types: dict[str, str] | None = None
    records: int = 150_000
    def __post_init__(self):
        self.topic_types = self.topic_types or {"/alpha": "test/Msg", "/beta": "test/Msg"}
        self.total_messages = self.records
    def messages(self):
        for i in range(self.records):
            topic = "/alpha" if i % 2 == 0 else "/beta"
            ordinal = i // 2
            jump = 10 if ordinal % 100 == 0 and ordinal else 1
            yield TimestampRecord(topic, ordinal * 1_000_000_000 + jump * 1_000_000_000)
    def close(self): pass


class CapturingWorkspace(analyzer.AnalysisWorkspace):
    instances = []
    def __init__(self, batch_size):
        super().__init__(batch_size); self.max_batch_seen = 0; self.__class__.instances.append(self)
    def add(self, topic, start_ns, end_ns):
        super().add(topic, start_ns, end_ns); self.max_batch_seen = max(self.max_batch_seen, len(self._batch))


def open_synthetic(_path):
    return SyntheticSource()


def test_high_volume_bounded_results_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(analyzer, "open_bag_source", open_synthetic)
    CapturingWorkspace.instances.clear()
    limits = AnalysisLimits(max_silence_windows_per_topic=3, max_incidents=4, gap_insert_batch_size=127)
    result = analyze_bag(tmp_path / "synthetic", limits=limits, workspace_factory=CapturingWorkspace)
    assert result.summary.total_messages == 150_000
    assert result.summary.topic_count == 2
    assert result.incident_count > result.returned_incident_count == 4
    assert all(t.silence_window_count > t.returned_silence_window_count == 3 for t in result.topics)
    assert len(result.incidents) == 4
    assert CapturingWorkspace.instances[0].max_batch_seen <= 127
    assert not CapturingWorkspace.instances[0].path.exists()


def test_global_ranking_and_zero_limits(monkeypatch, tmp_path):
    monkeypatch.setattr(analyzer, "open_bag_source", open_synthetic)
    ranked = analyze_bag(tmp_path / "ranked", limits=AnalysisLimits(max_silence_windows_per_topic=5, max_incidents=3))
    tuples = [(i.topic, i.duration_seconds, i.start_seconds) for i in ranked.incidents]
    assert tuples == sorted(tuples, key=lambda x: (-x[1], x[0], x[2]))
    zero = analyze_bag(tmp_path / "zero", limits=AnalysisLimits(max_silence_windows_per_topic=0, max_incidents=0))
    assert all(not t.silence_windows and t.returned_silence_window_count == 0 and t.silence_windows_truncated for t in zero.topics)
    assert zero.incidents == [] and zero.returned_incident_count == 0 and zero.incidents_truncated


def test_cleanup_on_scan_cancel_postprocess_cancel_and_error(monkeypatch, tmp_path):
    monkeypatch.setattr(analyzer, "open_bag_source", open_synthetic)
    CapturingWorkspace.instances.clear(); calls = [0]
    def cancel_scan():
        calls[0] += 1; return calls[0] > 2
    with pytest.raises(AnalysisCancelled): analyze_bag(tmp_path / "cancel", cancel_requested=cancel_scan, workspace_factory=CapturingWorkspace)
    assert not CapturingWorkspace.instances[-1].path.exists()
    CapturingWorkspace.instances.clear(); post_calls = [0]
    def cancel_post():
        post_calls[0] += 1; return post_calls[0] > 2
    with pytest.raises(AnalysisCancelled): analyze_bag(tmp_path / "post", cancel_requested=cancel_post, workspace_factory=CapturingWorkspace)
    assert not CapturingWorkspace.instances[-1].path.exists()
    class Broken(CapturingWorkspace):
        def details(self, *args): raise RuntimeError("synthetic workspace failure")
    with pytest.raises(RuntimeError): analyze_bag(tmp_path / "error", workspace_factory=Broken)
    assert not Broken.instances[-1].path.exists()


def test_result_size_stays_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(analyzer, "open_bag_source", open_synthetic)
    limits = AnalysisLimits(max_silence_windows_per_topic=2, max_incidents=2)
    one = analyze_bag(tmp_path / "one", limits=limits)
    two = analyze_bag(tmp_path / "two", limits=limits)
    one_json = json.dumps(jsonable_encoder(one)); two_json = json.dumps(jsonable_encoder(two))
    assert two.incident_count >= one.incident_count
    assert len(two.incidents) == len(one.incidents) == 2
    assert len(two_json) <= len(one_json) * 1.25 + 500
