"""FastAPI application for the Bag Doctor demo."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .analyzer import analyze_bag
from .schemas import AnalysisResult

PACKAGE_ROOT = Path(__file__).parent
DEMO_BAG = PACKAGE_ROOT / "data" / "failed_robot_demo"
WEB_ROOT = PACKAGE_ROOT / "web"

app = FastAPI(title="Bag Doctor", version="0.1.0")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/analyze/demo", response_model=AnalysisResult)
def analyze_demo() -> AnalysisResult:
    return analyze_bag(DEMO_BAG)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}

