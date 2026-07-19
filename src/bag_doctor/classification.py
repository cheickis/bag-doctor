"""Deterministic, conservative topic timing classification."""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field, model_validator


class TimingClassification(str, Enum):
    PERIODIC = "periodic"
    EVENT_DRIVEN = "event_driven"
    UNKNOWN = "unknown"
    USER_CONFIGURED = "user_configured"


class TopicTimingConfig(BaseModel):
    expected_rate_hz: float | None = Field(default=None, gt=0)
    gap_threshold_seconds: float | None = Field(default=None, gt=0)
    classification: TimingClassification | None = None

    @model_validator(mode="after")
    def validate_expectations(self) -> "TopicTimingConfig":
        if self.classification == TimingClassification.EVENT_DRIVEN and (
            self.expected_rate_hz is not None or self.gap_threshold_seconds is not None
        ):
            raise ValueError("event_driven topics cannot define periodic timing expectations")
        if self.classification == TimingClassification.PERIODIC and self.expected_rate_hz is None:
            raise ValueError("periodic configuration requires expected_rate_hz")
        return self


class TopicTimingConfiguration(BaseModel):
    topics: dict[str, TopicTimingConfig] = Field(default_factory=dict)


PERIODIC_MIN_MESSAGES = 20
PERIODIC_MIN_SPAN_SECONDS = 2.0
PERIODIC_MAX_RELATIVE_JITTER = 0.20
PERIODIC_MIN_STABLE_FRACTION = 0.80
KNOWN_EVENT_DRIVEN_TOPICS = frozenset({"/rosout"})


def classify_topic(
    topic: str,
    *,
    message_count: int,
    gap_count: int,
    median_gap_ns: int | None,
    mean_gap_ns: float | None,
    stable_gap_fraction: float | None = None,
    first_timestamp_ns: int,
    last_timestamp_ns: int,
    configuration: TopicTimingConfiguration | None = None,
) -> tuple[TimingClassification, int | None, int | None]:
    """Return classification, expected period, and configured gap threshold (ns)."""
    configured = (configuration.topics.get(topic) if configuration else None)
    if configured is not None:
        if configured.classification in (TimingClassification.EVENT_DRIVEN, TimingClassification.UNKNOWN):
            return configured.classification, None, None
        period = int(round(1_000_000_000 / configured.expected_rate_hz)) if configured.expected_rate_hz else None
        if configured.classification == TimingClassification.PERIODIC:
            return TimingClassification.PERIODIC, period, int(round(configured.gap_threshold_seconds * 1_000_000_000)) if configured.gap_threshold_seconds else None
        return TimingClassification.USER_CONFIGURED, period, int(round(configured.gap_threshold_seconds * 1_000_000_000)) if configured.gap_threshold_seconds else None
    if topic in KNOWN_EVENT_DRIVEN_TOPICS:
        return TimingClassification.EVENT_DRIVEN, None, None
    span = (last_timestamp_ns - first_timestamp_ns) / 1_000_000_000
    stable = (
        message_count >= PERIODIC_MIN_MESSAGES
        and gap_count >= PERIODIC_MIN_MESSAGES - 1
        and span >= PERIODIC_MIN_SPAN_SECONDS
        and median_gap_ns is not None
        and (
            stable_gap_fraction is not None
            and stable_gap_fraction >= PERIODIC_MIN_STABLE_FRACTION
            or mean_gap_ns is not None
            and mean_gap_ns > 0
            and abs(mean_gap_ns - median_gap_ns) / median_gap_ns <= PERIODIC_MAX_RELATIVE_JITTER
        )
    )
    if stable:
        return TimingClassification.PERIODIC, median_gap_ns, None
    return TimingClassification.UNKNOWN, median_gap_ns, None
