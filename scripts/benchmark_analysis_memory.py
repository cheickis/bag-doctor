"""Bounded-analysis benchmark; writes no repository artifacts."""
from __future__ import annotations
import json, time, tracemalloc
from pathlib import Path
from fastapi.encoders import jsonable_encoder
import bag_doctor.analyzer as analyzer
from bag_doctor.analyzer import AnalysisLimits, analyze_bag
from bag_doctor.ingestion.reader import TimestampRecord

class LazySource:
    storage_format = "synthetic"
    total_messages = 500_000
    topic_types = {f"/topic_{i}": "benchmark/Msg" for i in range(4)}
    def messages(self):
        for i in range(self.total_messages):
            topic = f"/topic_{i % 4}"
            ordinal = i // 4
            jump = 10 if ordinal % 100 == 0 and ordinal else 1
            yield TimestampRecord(topic, ordinal * 1_000_000_000 + jump * 1_000_000_000)
    def close(self): pass

class MeasuringWorkspace(analyzer.AnalysisWorkspace):
    peak = 0
    def flush(self):
        super().flush()
        self.__class__.peak = max(self.__class__.peak, self.footprint_bytes())

def main():
    analyzer.open_bag_source = lambda path: LazySource()
    limits = AnalysisLimits(max_silence_windows_per_topic=50, max_incidents=200)
    tracemalloc.start(); started = time.perf_counter()
    result = analyze_bag(Path("/tmp/bag-doctor-benchmark-source"), limits=limits, workspace_factory=MeasuringWorkspace)
    elapsed = time.perf_counter() - started
    _, peak_python = tracemalloc.get_traced_memory(); tracemalloc.stop()
    payload = json.dumps(jsonable_encoder(result), separators=(",", ":"))
    print(f"message_count {result.summary.total_messages}")
    print(f"topic_count {result.summary.topic_count}")
    print(f"elapsed_seconds {elapsed:.3f}")
    print(f"peak_python_memory_bytes {peak_python}")
    print(f"workspace_peak_bytes {MeasuringWorkspace.peak}")
    print(f"result_json_bytes {len(payload.encode())}")
    print(f"exact_topic_finding_count {sum(t.silence_window_count for t in result.topics)}")
    print(f"returned_topic_finding_count {sum(t.returned_silence_window_count for t in result.topics)}")
    print(f"exact_global_incident_count {result.incident_count}")
    print(f"returned_global_incident_count {result.returned_incident_count}")

if __name__ == "__main__": main()
