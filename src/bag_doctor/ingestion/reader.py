"""Normalized, read-only ROS 2 timestamp sources."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Protocol

from rosbags.rosbag2 import Reader
from mcap.reader import make_reader
from .extractor import InputValidationError


@dataclass(frozen=True)
class TimestampRecord:
    topic: str
    timestamp_ns: int


class BagSource(Protocol):
    storage_format: str
    topic_types: Mapping[str, str]
    total_messages: int | None
    def messages(self) -> Iterator[TimestampRecord]: ...
    def close(self) -> None: ...


class Rosbag2DirectorySource:
    def __init__(self, path: Path):
        self.reader = Reader(path); self.reader.open()
        self.storage_format = "sqlite3"
        metadata = path / "metadata.yaml"
        if metadata.exists() and "storage_identifier: mcap" in metadata.read_text(): self.storage_format = "mcap"
        self.topic_types = {c.topic: c.msgtype for c in self.reader.connections}
        self.total_messages = self.reader.message_count
    def messages(self):
        for connection, timestamp, _ in self.reader.messages():
            yield TimestampRecord(connection.topic, timestamp)
    def close(self): self.reader.close()


class StandaloneMcapSource:
    def __init__(self, path: Path):
        self.file = path.open("rb"); self.reader = make_reader(self.file); self.storage_format = "ros2_mcap"
        self.topic_types = {}
        summary = self.reader.get_summary()
        if summary:
            for channel in summary.channels.values():
                schema = summary.schemas.get(channel.schema_id) if channel.schema_id else None
                self.topic_types[channel.topic] = schema.name if schema and schema.name else "unknown"
            self.total_messages = summary.statistics.message_count if summary.statistics else None
        else: self.total_messages = None
    def messages(self):
        for schema, channel, message in self.reader.iter_messages():
            self.topic_types.setdefault(channel.topic, schema.name if schema and schema.name else "unknown")
            yield TimestampRecord(channel.topic, message.log_time)
    def close(self): self.file.close()


class StandaloneSqliteSource:
    def __init__(self, path: Path):
        try:
            self.connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
            tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing_tables = {"topics", "messages"} - tables
            if missing_tables:
                raise InputValidationError("SQLite file is not a ROS 2 bag: topics/messages tables are missing")
            required = {"topics": {"id", "name", "type"}, "messages": {"topic_id", "timestamp"}}
            for table, required_columns in required.items():
                columns = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
                missing_columns = sorted(required_columns - columns)
                if missing_columns:
                    raise InputValidationError(f"Invalid ROS 2 SQLite bag: table '{table}' is missing required columns: {', '.join(missing_columns)}")
        except sqlite3.DatabaseError as exc:
            if hasattr(self, "connection"): self.connection.close()
            raise InputValidationError(f"Invalid ROS 2 SQLite bag: {exc}") from exc
        except InputValidationError:
            self.connection.close()
            raise
        self.storage_format = "ros2_sqlite_standalone"
        self.topic_types = {name: msgtype for name, msgtype in self.connection.execute("SELECT name, type FROM topics")}
        self.total_messages = self.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    def messages(self):
        query = "SELECT topics.name, messages.timestamp FROM messages JOIN topics ON topics.id = messages.topic_id ORDER BY messages.timestamp"
        for topic, timestamp in self.connection.execute(query): yield TimestampRecord(topic, timestamp)
    def close(self): self.connection.close()


def open_bag_source(path: Path) -> BagSource:
    path = Path(path)
    if path.is_dir(): return Rosbag2DirectorySource(path)
    if path.suffix.lower() == ".mcap": return StandaloneMcapSource(path)
    if path.suffix.lower() == ".db3": return StandaloneSqliteSource(path)
    raise ValueError("Unsupported ROS 2 bag input")


class BagReader:
    """Compatibility wrapper retained for callers outside the analyzer."""
    def __init__(self, path: Path): self.source = open_bag_source(path)
    def __enter__(self): return self
    def __exit__(self, *args): self.source.close()
    @property
    def connections(self): return ()
    def messages(self):
        for record in self.source.messages(): yield (type("Connection", (), {"topic": record.topic, "msgtype": self.source.topic_types.get(record.topic, "unknown")})(), record.timestamp_ns, None)
