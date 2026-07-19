"""Streaming, deterministic analysis of rosbag2 timestamps."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import median

from .schemas import AnalysisResult, BagSummary, SilenceWindow, TopicHealth
from .ingestion.reader import BagReader

NANOSECONDS = 1_000_000_000


def _seconds(value_ns: int) -> float:
    return round(value_ns / NANOSECONDS, 6)


def analyze_bag(
    path: Path,
    *,
    silence_multiplier: float = 5.0,
    minimum_silence_seconds: float = 1.0,
) -> AnalysisResult:
    """Analyze connection metadata and timestamps without decoding message bodies.

    Only timestamp deltas are retained per topic. This is substantially smaller than
    decoded messages and is sufficient for all metrics in this vertical slice.
    """
    path = Path(path)
    deltas: dict[str, list[int]] = defaultdict(list)
    gaps: dict[str, list[tuple[int, int]]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    previous: dict[str, int] = {}
    first_timestamp: int | None = None
    last_timestamp: int | None = None

    with BagReader(path) as reader:
        topic_types = {connection.topic: connection.msgtype for connection in reader.connections}
        storage_format = "mcap" if any(path.glob("*.mcap")) else "sqlite3"

        for connection, timestamp, _rawdata in reader.messages():
            topic = connection.topic
            counts[topic] += 1
            first_timestamp = timestamp if first_timestamp is None else min(first_timestamp, timestamp)
            last_timestamp = timestamp if last_timestamp is None else max(last_timestamp, timestamp)
            if topic in previous:
                delta = timestamp - previous[topic]
                deltas[topic].append(delta)
                gaps[topic].append((previous[topic], timestamp))
            previous[topic] = timestamp

    if first_timestamp is None or last_timestamp is None:
        raise ValueError(f"Bag contains no messages: {path}")

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
