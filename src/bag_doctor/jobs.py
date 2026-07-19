"""Small in-process job registry for local, read-only analysis."""
from __future__ import annotations
import hashlib, json, threading, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .analyzer import analyze_bag
from .ingestion.detector import InputKind, detect_input

ANALYZER_VERSION = "2a"

@dataclass
class Job:
    id: str; path: Path; state: str = "queued"; stage: str = "metadata inventory"
    processed_messages: int = 0; total_messages: int | None = None; percent: float = 0
    started: float = field(default_factory=time.monotonic); elapsed_seconds: float = 0
    eta_seconds: float | None = None; result: Any = None; error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

_jobs: dict[str, Job] = {}; _cache: dict[str, Any] = {}; _lock = threading.Lock()

def cache_key(path: Path) -> str:
    files = sorted([p for p in ([path] if path.is_file() else list(path.rglob("*.db3")) + list(path.rglob("*.mcap")) + list(path.rglob("metadata.yaml"))) if p.exists()])
    h = hashlib.sha256(ANALYZER_VERSION.encode())
    for f in files:
        s = f.stat(); h.update(str(f).encode()); h.update(f"{s.st_size}:{s.st_mtime_ns}".encode());
        if f.name == "metadata.yaml": h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()

def _run(job: Job):
    try:
        job.state = "running"; job.stage = "timestamp-only streaming scan"
        key = cache_key(job.path)
        if key in _cache:
            job.result = _cache[key]; job.percent = 100; job.state = "completed"; return
        if job.cancel.is_set(): job.state = "cancelled"; return
        job.result = analyze_bag(job.path)
        _cache[key] = job.result; job.percent = 100; job.stage = "completed"; job.state = "completed"
    except Exception as exc:
        job.error = str(exc); job.state = "error"
    finally: job.elapsed_seconds = time.monotonic() - job.started

def create_job(path: Path) -> Job:
    jid = hashlib.sha1(f"{path}:{time.time_ns()}".encode()).hexdigest()[:16]
    job = Job(jid, path)
    _jobs[jid] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job

def get_job(jid: str) -> Job | None: return _jobs.get(jid)
