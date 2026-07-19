"""Streaming, deterministic analysis of rosbag2 timestamps."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import median
from collections.abc import Callable
from dataclasses import dataclass

from .schemas import AnalysisResult, BagSummary, SilenceWindow, TopicHealth
from .ingestion.reader import open_bag_source
from .analysis_workspace import AnalysisWorkspace

NANOSECONDS = 1_000_000_000


class AnalysisCancelled(Exception):
    """Raised when an active bag analysis is cooperatively cancelled."""


@dataclass(frozen=True)
class AnalysisProgress:
    processed_messages: int
    total_messages: int | None


ProgressCallback = Callable[[AnalysisProgress], None]


@dataclass(frozen=True)
class AnalysisLimits:
    max_silence_windows_per_topic: int = 50
    max_incidents: int = 200
    gap_insert_batch_size: int = 10_000
    def __post_init__(self):
        if self.max_silence_windows_per_topic < 0 or self.max_incidents < 0 or self.gap_insert_batch_size <= 0:
            raise ValueError("Analysis limits must be nonnegative, with a positive batch size")


def _seconds(value_ns: int) -> float:
    return round(value_ns / NANOSECONDS, 6)


def analyze_bag(
    path: Path,
    *,
    silence_multiplier: float = 5.0,
    minimum_silence_seconds: float = 1.0,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
    limits: AnalysisLimits | None = None,
    workspace_factory: Callable[[int], object] | None = None,
) -> AnalysisResult:
    """Analyze connection metadata and timestamps without decoding message bodies.

    Only timestamp deltas are retained per topic. This is substantially smaller than
    decoded messages and is sufficient for all metrics in this vertical slice.
    """
    path = Path(path)
    limits = limits or AnalysisLimits()
    if cancel_requested and cancel_requested():
        raise AnalysisCancelled()
    counts: dict[str, int] = defaultdict(int)
    previous: dict[str, int] = {}
    first_timestamp: int | None = None
    last_timestamp: int | None = None

    source = open_bag_source(path)
    workspace = (workspace_factory or AnalysisWorkspace)(limits.gap_insert_batch_size)
    try:
        topic_types = dict(source.topic_types)
        storage_format = source.storage_format
        total_messages = source.total_messages
        if total_messages is not None and total_messages < 0:
            raise ValueError("Bag source reported an invalid negative message total")
        processed_messages = 0
        if progress_callback:
            progress_callback(AnalysisProgress(0, total_messages))
        for record in source.messages():
            if cancel_requested and cancel_requested():
                raise AnalysisCancelled()
            topic = record.topic
            timestamp = record.timestamp_ns
            counts[topic] += 1
            first_timestamp = timestamp if first_timestamp is None else min(first_timestamp, timestamp)
            last_timestamp = timestamp if last_timestamp is None else max(last_timestamp, timestamp)
            if topic in previous:
                delta = timestamp - previous[topic]
                workspace.add(topic, previous[topic], timestamp)
            previous[topic] = timestamp
            processed_messages += 1
            if progress_callback and processed_messages % 5000 == 0:
                progress_callback(AnalysisProgress(processed_messages, total_messages))

    except Exception:
        workspace.close()
        raise
    finally:
        source.close()

    if first_timestamp is None or last_timestamp is None:
        raise ValueError(f"Bag contains no messages: {path}")
    if cancel_requested and cancel_requested():
        raise AnalysisCancelled()
    if progress_callback:
        progress_callback(AnalysisProgress(processed_messages, total_messages))

    workspace.flush()
    topics: list[TopicHealth] = []
    thresholds: dict[str, int] = {}
    exact_incident_count = 0
    try:
      for topic in sorted(topic_types):
        if cancel_requested and cancel_requested(): raise AnalysisCancelled()
        median_delta = workspace.median(topic)
        threshold = None
        if median_delta:
            threshold = max(int(minimum_silence_seconds * NANOSECONDS), int(median_delta * silence_multiplier))
            thresholds[topic] = threshold

        windows: list[SilenceWindow] = []
        silence_count = workspace.count(topic, threshold) if median_delta and threshold else 0
        exact_incident_count += silence_count
        if median_delta and threshold:
            for gap_start, gap_end, gap in workspace.details(topic, threshold, limits.max_silence_windows_per_topic):
                windows.append(SilenceWindow(topic=topic, start_seconds=_seconds(gap_start - first_timestamp), end_seconds=_seconds(gap_end - first_timestamp), duration_seconds=_seconds(gap), expected_period_seconds=_seconds(median_delta)))

        topics.append(
            TopicHealth(
                topic=topic,
                message_type=topic_types[topic],
                message_count=counts[topic],
                median_rate_hz=round(NANOSECONDS / median_delta, 3) if median_delta else None,
                maximum_gap_seconds=_seconds(workspace.db.execute("SELECT MAX(duration_ns) FROM gaps WHERE topic=?", (topic,)).fetchone()[0]) if workspace.db.execute("SELECT COUNT(*) FROM gaps WHERE topic=?", (topic,)).fetchone()[0] else None,
                silence_windows=windows,
                silence_window_count=silence_count,
                returned_silence_window_count=len(windows),
                silence_windows_truncated=silence_count > len(windows),
            )
        )

      if cancel_requested and cancel_requested():
          raise AnalysisCancelled()
      global_details = [SilenceWindow(topic=topic, start_seconds=_seconds(start), end_seconds=_seconds(end), duration_seconds=_seconds(duration), expected_period_seconds=_seconds(workspace.median(topic) or 0)) for topic, start, end, duration in workspace.global_details(thresholds, limits.max_incidents)]
      return AnalysisResult(
        summary=BagSummary(
            bag_name=path.name,
            storage_format=storage_format,
            duration_seconds=_seconds(last_timestamp - first_timestamp),
            start_time_ns=first_timestamp,
            end_time_ns=last_timestamp,
            total_messages=sum(counts.values()),
            topic_count=len(topic_types),
        ),
        topics=topics,
        incidents=global_details,
        incident_count=exact_incident_count,
        returned_incident_count=len(global_details),
        incidents_truncated=exact_incident_count > len(global_details),
      )
    finally:
      workspace.close()
