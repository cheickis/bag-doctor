"""Streaming, deterministic analysis of rosbag2 timestamps."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import median
from collections.abc import Callable
from dataclasses import dataclass

from .schemas import AnalysisResult, BagSummary, SilenceWindow, TopicHealth
from .ingestion.reader import open_bag_source

NANOSECONDS = 1_000_000_000


class AnalysisCancelled(Exception):
    """Raised when an active bag analysis is cooperatively cancelled."""


@dataclass(frozen=True)
class AnalysisProgress:
    processed_messages: int
    total_messages: int | None


ProgressCallback = Callable[[AnalysisProgress], None]


def _seconds(value_ns: int) -> float:
    return round(value_ns / NANOSECONDS, 6)


def analyze_bag(
    path: Path,
    *,
    silence_multiplier: float = 5.0,
    minimum_silence_seconds: float = 1.0,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AnalysisResult:
    """Analyze connection metadata and timestamps without decoding message bodies.

    Only timestamp deltas are retained per topic. This is substantially smaller than
    decoded messages and is sufficient for all metrics in this vertical slice.
    """
    path = Path(path)
    if cancel_requested and cancel_requested():
        raise AnalysisCancelled()
    deltas: dict[str, list[int]] = defaultdict(list)
    gaps: dict[str, list[tuple[int, int]]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    previous: dict[str, int] = {}
    first_timestamp: int | None = None
    last_timestamp: int | None = None

    source = open_bag_source(path)
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
                deltas[topic].append(delta)
                gaps[topic].append((previous[topic], timestamp))
            previous[topic] = timestamp
            processed_messages += 1
            if progress_callback and processed_messages % 5000 == 0:
                progress_callback(AnalysisProgress(processed_messages, total_messages))

    finally:
        source.close()

    if first_timestamp is None or last_timestamp is None:
        raise ValueError(f"Bag contains no messages: {path}")
    if cancel_requested and cancel_requested():
        raise AnalysisCancelled()
    if progress_callback:
        progress_callback(AnalysisProgress(processed_messages, total_messages))

    topics: list[TopicHealth] = []
    incidents: list[SilenceWindow] = []
    for topic in sorted(topic_types):
        topic_deltas = deltas[topic]
        median_delta = int(median(topic_deltas)) if topic_deltas else None
        threshold = None
        if median_delta:
            threshold = max(int(minimum_silence_seconds * NANOSECONDS), int(median_delta * silence_multiplier))

        windows: list[SilenceWindow] = []
        if median_delta and threshold:
            for gap_start, gap_end in gaps[topic]:
                gap = gap_end - gap_start
                if gap >= threshold:
                    window = SilenceWindow(
                        topic=topic,
                        start_seconds=_seconds(gap_start - first_timestamp),
                        end_seconds=_seconds(gap_end - first_timestamp),
                        duration_seconds=_seconds(gap),
                        expected_period_seconds=_seconds(median_delta),
                    )
                    windows.append(window)
                    incidents.append(window)

        topics.append(
            TopicHealth(
                topic=topic,
                message_type=topic_types[topic],
                message_count=counts[topic],
                median_rate_hz=round(NANOSECONDS / median_delta, 3) if median_delta else None,
                maximum_gap_seconds=_seconds(max(topic_deltas)) if topic_deltas else None,
                silence_windows=windows,
            )
        )

    if cancel_requested and cancel_requested():
        raise AnalysisCancelled()
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
        incidents=sorted(incidents, key=lambda item: (item.start_seconds, item.topic)),
    )
