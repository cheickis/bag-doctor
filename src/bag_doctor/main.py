"""FastAPI application for the Bag Doctor demo."""

from pathlib import Path
import secrets

from fastapi import FastAPI, File, HTTPException, UploadFile, Request, Query
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
import asyncio, json
from fastapi.responses import FileResponse

from .analyzer import analyze_bag
from .schemas import AnalysisResult
from .ingestion import InputValidationError, stage_upload
from .jobs import create_job, get_job, request_cancel, Job, _jobs, _lock
from .investigator import investigate, InvestigationResult

PACKAGE_ROOT = Path(__file__).parent
DEMO_BAG = PACKAGE_ROOT / "data" / "failed_robot_demo"
WEB_ROOT = PACKAGE_ROOT / "web"  # Legacy vanilla UI source; intentionally not served at runtime.
FRONTEND_DIST = PACKAGE_ROOT / "web" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"

app = FastAPI(title="Bag Doctor", version="0.1.0")
app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS, check_dir=False), name="frontend-assets")

class LocalRequest(BaseModel):
    path: str

class InvestigationRequest(BaseModel):
    question: str
    max_tool_calls: int = 6


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    if not FRONTEND_INDEX.is_file():
        raise HTTPException(503, "Frontend production build is unavailable")
    return FileResponse(FRONTEND_INDEX)


@app.get("/api/analyze/demo", response_model=AnalysisResult)
def analyze_demo() -> AnalysisResult:
    return analyze_bag(DEMO_BAG)

@app.get("/api/analyze/demo/job")
def analyze_demo_job() -> dict:
    try:
        result = analyze_bag(DEMO_BAG)
    except Exception as exc:
        raise HTTPException(500, "Demo analysis could not be completed") from exc
    job = Job(
        f"demo-{secrets.token_hex(8)}", DEMO_BAG, state="completed", stage="completed",
        processed_messages=result.summary.total_messages,
        total_messages=result.summary.total_messages, percent=100, result=result,
    )
    with _lock:
        while job.id in _jobs:
            job.id = f"demo-{secrets.token_hex(8)}"
        _jobs[job.id] = job
    return job_payload(job, include_result=False)

@app.post("/api/analyze/jobs/{job_id}/investigate", response_model=InvestigationResult)
def investigate_job(job_id: str, request: InvestigationRequest) -> InvestigationResult:
    try:
        return investigate(job_id, request.question, max_tool_calls=request.max_tool_calls)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        status = 503 if "OPENAI_API_KEY" in str(exc) else 409 if "complete" in str(exc) else 502
        raise HTTPException(status, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post("/api/analyze/local")
def analyze_local(request: LocalRequest) -> dict:
    path = Path(request.path).expanduser()
    if not path.is_absolute() or not path.exists():
        raise HTTPException(400, "Local bag path must be an existing absolute path")
    if path.is_dir() and not ((path / "metadata.yaml").exists() and (list(path.glob("*.db3")) or list(path.glob("*.mcap")))):
        raise HTTPException(400, "Unsupported local path: expected metadata.yaml and bag files")
    if path.is_file() and path.suffix.lower() not in {".mcap", ".db3"}:
        raise HTTPException(415, "Unsupported local path extension")
    job = create_job(path)
    return {"job_id": job.id, "state": job.state}

@app.get("/api/analyze/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job: raise HTTPException(404, "Unknown analysis job")
    return job_payload(job, include_result=True)

@app.get("/api/analyze/jobs/{job_id}/evidence")
def job_evidence(job_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), topic: str | None = None, evidence_type: str | None = None) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown analysis job")
    if job.result is None:
        raise HTTPException(409, "Evidence is not available until analysis completes")
    items = [item for health in job.result.topics for item in health.silence_windows]
    seen = {item.evidence_id for item in items}
    items.extend(item for item in job.result.incidents if item.evidence_id not in seen)
    if topic:
        items = [item for item in items if item.topic == topic]
    if evidence_type and evidence_type != "silence_window":
        items = []
    items.sort(key=lambda item: (-item.duration_seconds, item.topic, item.start_seconds, item.evidence_id or ""))
    page = items[offset:offset + limit]
    return {"total_count": len(items), "returned_count": len(page), "offset": offset, "limit": limit, "items": [item.model_dump(mode="json") for item in page]}

@app.get("/api/analyze/jobs/{job_id}/evidence/{evidence_id}")
def job_evidence_item(job_id: str, evidence_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown analysis job")
    if job.result is None:
        raise HTTPException(409, "Evidence is not available until analysis completes")
    candidates = [item for health in job.result.topics for item in health.silence_windows] + list(job.result.incidents)
    for item in candidates:
        if item.evidence_id == evidence_id:
            return item.model_dump(mode="json")
    raise HTTPException(404, "Unknown evidence ID")

def job_payload(job, *, include_result: bool) -> dict:
    """Shared, FastAPI-safe representation of a job."""
    payload = {"job_id": job.id, "state": job.state, "stage": job.stage,
        "processed_messages": job.processed_messages, "total_messages": job.total_messages,
        "percent_complete": job.percent, "elapsed_seconds": job.elapsed_seconds,
        "estimated_remaining_seconds": job.eta_seconds, "has_result": job.result is not None,
        "error": job.error}
    if include_result:
        payload["result"] = jsonable_encoder(job.result) if job.result is not None else None
    return payload

@app.post("/api/analyze/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = request_cancel(job_id)
    if not job: raise HTTPException(404, "Unknown analysis job")
    return {"job_id": job.id, "state": job.state}

@app.get("/api/analyze/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    if not get_job(job_id): raise HTTPException(404, "Unknown analysis job")
    async def events():
        while True:
            job = get_job(job_id)
            if await request.is_disconnected():
                return
            event = "completed" if job.state == "completed" else "job-error" if job.state == "error" else "cancelled" if job.state == "cancelled" else "progress"
            yield f"event: {event}\ndata: {json.dumps(job_payload(job, include_result=False), separators=(',', ':'))}\n\n"
            if event != "progress":
                return
            await asyncio.sleep(.25)
            yield ": keep-alive\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "Connection":"keep-alive", "X-Accel-Buffering":"no"})


@app.post("/api/analyze/upload", response_model=AnalysisResult)
async def analyze_upload(file: UploadFile = File(...)) -> AnalysisResult:
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".mcap", ".db3", ".zip"}:
        raise HTTPException(415, "Unsupported upload extension; use .mcap, .db3, or .zip")
    import tempfile
    with tempfile.NamedTemporaryFile(prefix="bag-doctor-upload-", suffix=suffix) as incoming:
        total = 0
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > 512 * 1024 * 1024:
                raise HTTPException(413, "Upload exceeds maximum size of 512 MiB")
            incoming.write(chunk)
        incoming.flush()
        try:
            with stage_upload(Path(incoming.name), filename) as staged:
                result = analyze_bag(staged.path)
                result.summary.storage_format = staged.kind.value
                result.summary.original_filename = staged.original_filename
                result.summary.metadata_available = staged.metadata_available
                result.summary.split_file_count = staged.split_file_count
                result.summary.warnings = staged.warnings
                return result
        except (InputValidationError, ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}
