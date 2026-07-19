"""Small in-process job registry for local, read-only analysis."""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analyzer import AnalysisCancelled, AnalysisProgress, analyze_bag

ANALYZER_VERSION = "2a"
TERMINAL_STATES = {"completed", "error", "cancelled"}


@dataclass
class Job:
    id: str
    path: Path
    state: str = "queued"
    stage: str = "metadata inventory"
    processed_messages: int = 0
    total_messages: int | None = None
    percent: float | None = 0
    started: float = field(default_factory=time.monotonic)
    elapsed_seconds: float = 0
    eta_seconds: float | None = None
    result: Any = None
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


_jobs: dict[str, Job] = {}
_cache: dict[str, Any] = {}
_lock = threading.Lock()


def cache_key(path: Path) -> str:
    files = sorted(
        p
        for p in (
            [path]
            if path.is_file()
            else list(path.rglob("*.db3"))
            + list(path.rglob("*.mcap"))
            + list(path.rglob("metadata.yaml"))
        )
        if p.exists()
    )
    digest = hashlib.sha256(ANALYZER_VERSION.encode())
    for file in files:
        stat = file.stat()
        digest.update(str(file).encode())
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        if file.name == "metadata.yaml":
            digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def _run(job: Job) -> None:
    try:
        with _lock:
            if job.cancel.is_set():
                job.state = "cancelled"
                return
            job.state = "running"
            job.stage = "timestamp-only streaming scan"

        key = cache_key(job.path)
        with _lock:
            if job.cancel.is_set() or job.state == "cancelling":
                job.state = "cancelled"
                return
            cached = _cache.get(key)
        if cached is not None:
            with _lock:
                if job.cancel.is_set() or job.state == "cancelling":
                    job.state = "cancelled"
                    return
                job.result = cached
                job.total_messages = cached.summary.total_messages
                job.processed_messages = cached.summary.total_messages
                job.percent = 100
                job.stage = "completed"
                job.state = "completed"
            return

        result = analyze_bag(
            job.path,
            cancel_requested=job.cancel.is_set,
            progress_callback=lambda progress: _update_progress(job, progress),
        )
        with _lock:
            if job.cancel.is_set() or job.state == "cancelling":
                job.state = "cancelled"
                return
            _cache[key] = result
            job.result = result
            job.processed_messages = result.summary.total_messages
            job.total_messages = result.summary.total_messages
            job.percent = 100
            job.stage = "completed"
            job.state = "completed"
    except AnalysisCancelled:
        with _lock:
            job.result = None
            job.error = None
            job.state = "cancelled"
    except Exception as exc:
        with _lock:
            if job.cancel.is_set() or job.state == "cancelling":
                job.result = None
                job.error = None
                job.state = "cancelled"
            else:
                job.error = str(exc)
                job.state = "error"
    finally:
        with _lock:
            job.elapsed_seconds = time.monotonic() - job.started


def create_job(path: Path) -> Job:
    job_id = hashlib.sha1(f"{path}:{time.time_ns()}".encode()).hexdigest()[:16]
    job = Job(job_id, path)
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job


def _update_progress(job: Job, progress: AnalysisProgress) -> None:
    with _lock:
        job.processed_messages = max(0, progress.processed_messages)
        job.total_messages = progress.total_messages
        job.elapsed_seconds = max(job.elapsed_seconds, time.monotonic() - job.started)
        if job.total_messages is not None and job.total_messages > 0:
            raw_percent = job.processed_messages / job.total_messages * 100
            job.percent = min(99.9, max(0.0, raw_percent))
            if job.processed_messages > 0 and job.processed_messages < job.total_messages and job.elapsed_seconds > 0:
                rate = job.processed_messages / job.elapsed_seconds
                job.eta_seconds = max(0.0, (job.total_messages - job.processed_messages) / rate)
            else:
                job.eta_seconds = None
        else:
            job.percent = None
            job.eta_seconds = None


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def request_cancel(job_id: str) -> Job | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.state in TERMINAL_STATES:
            return job
        job.cancel.set()
        job.state = "cancelling"
        return job
