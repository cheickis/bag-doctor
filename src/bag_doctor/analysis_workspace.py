"""Ephemeral disk-backed storage for exact gap statistics."""
from __future__ import annotations
import sqlite3
import tempfile
from pathlib import Path

class AnalysisWorkspace:
    def __init__(self, batch_size: int = 10_000):
        self._tmp = tempfile.TemporaryDirectory(prefix="bag-doctor-analysis-")
        self.path = Path(self._tmp.name) / "gaps.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.db.execute("CREATE TABLE gaps(topic TEXT NOT NULL, start_ns INTEGER NOT NULL, end_ns INTEGER NOT NULL, duration_ns INTEGER NOT NULL)")
        self.db.execute("CREATE INDEX gaps_topic_duration ON gaps(topic, duration_ns DESC, start_ns ASC)")
        self.db.execute("CREATE INDEX gaps_topic ON gaps(topic)")
        self.batch_size = batch_size
        self._batch = []
    def add(self, topic: str, start_ns: int, end_ns: int) -> None:
        self._batch.append((topic, start_ns, end_ns, end_ns - start_ns))
        if len(self._batch) >= self.batch_size: self.flush()
    def flush(self) -> None:
        if self._batch:
            self.db.executemany("INSERT INTO gaps VALUES (?,?,?,?)", self._batch)
            self.db.commit(); self._batch.clear()
    def count(self, topic: str, threshold: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM gaps WHERE topic=? AND duration_ns>=?", (topic, threshold)).fetchone()[0]
    def median(self, topic: str) -> int | None:
        count = self.db.execute("SELECT COUNT(*) FROM gaps WHERE topic=?", (topic,)).fetchone()[0]
        if not count: return None
        offset = (count - 1) // 2
        row = self.db.execute("SELECT duration_ns FROM gaps WHERE topic=? ORDER BY duration_ns LIMIT 2 OFFSET ?", (topic, offset)).fetchall()
        return int(sum(item[0] for item in row) / len(row))
    def details(self, topic: str, threshold: int, limit: int):
        return self.db.execute("SELECT start_ns,end_ns,duration_ns FROM gaps WHERE topic=? AND duration_ns>=? ORDER BY duration_ns DESC,start_ns ASC LIMIT ?", (topic, threshold, limit)).fetchall()
    def global_details(self, thresholds: dict[str, int], limit: int):
        self.db.execute("CREATE TEMP TABLE thresholds(topic TEXT PRIMARY KEY, threshold_ns INTEGER NOT NULL)")
        self.db.executemany("INSERT INTO thresholds VALUES (?,?)", thresholds.items())
        return self.db.execute("SELECT g.topic,g.start_ns,g.end_ns,g.duration_ns FROM gaps g JOIN thresholds t ON t.topic=g.topic WHERE g.duration_ns>=t.threshold_ns ORDER BY g.duration_ns DESC,g.topic ASC,g.start_ns ASC LIMIT ?", (limit,)).fetchall()
    def close(self) -> None:
        self.flush(); self.db.close(); self._tmp.cleanup()
    def footprint_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.path.parent.glob(self.path.name + "*") if p.exists())
