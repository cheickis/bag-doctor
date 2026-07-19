"""API models for deterministic bag analysis results."""

from pydantic import BaseModel, Field
from .classification import TimingClassification


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
    timing_classification: TimingClassification = TimingClassification.UNKNOWN
    silence_windows: list[SilenceWindow] = Field(default_factory=list)
    silence_window_count: int = 0
    returned_silence_window_count: int = 0
    silence_windows_truncated: bool = False


class BagSummary(BaseModel):
    bag_name: str
    storage_format: str
    duration_seconds: float
    start_time_ns: int
    end_time_ns: int
    total_messages: int
    topic_count: int
    original_filename: str | None = None
    metadata_available: bool = True
    split_file_count: int = 1
    warnings: list[str] = Field(default_factory=list)
    analysis_capabilities: list[str] = Field(default_factory=lambda: [
        "topic_inventory", "message_counts", "bag_duration", "median_topic_rate",
        "maximum_inter_message_gap", "silence_window_detection",
    ])


class AnalysisResult(BaseModel):
    summary: BagSummary
    topics: list[TopicHealth]
    incidents: list[SilenceWindow]
    incident_count: int = 0
    returned_incident_count: int = 0
    incidents_truncated: bool = False
