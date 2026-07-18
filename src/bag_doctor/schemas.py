"""API models for deterministic bag analysis results."""

from pydantic import BaseModel, Field


class SilenceWindow(BaseModel):
    topic: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    expected_period_seconds: float


class TopicHealth(BaseModel):
    topic: str
    message_type: str
    message_count: int
    median_rate_hz: float | None
    maximum_gap_seconds: float | None
    silence_windows: list[SilenceWindow] = Field(default_factory=list)


class BagSummary(BaseModel):
    bag_name: str
    storage_format: str
    duration_seconds: float
    start_time_ns: int
    end_time_ns: int
    total_messages: int
    topic_count: int


class AnalysisResult(BaseModel):
    summary: BagSummary
    topics: list[TopicHealth]
    incidents: list[SilenceWindow]

