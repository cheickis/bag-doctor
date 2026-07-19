from pathlib import Path
import io, zipfile

import pytest
from fastapi.testclient import TestClient

from bag_doctor.analyzer import analyze_bag
from bag_doctor.ingestion.extractor import InputValidationError, stage_upload
from bag_doctor.main import app

ROOT = Path(__file__).parents[1]
MCAP = ROOT / "src/bag_doctor/data/failed_robot_demo/failed_robot_demo.mcap"
DB3 = ROOT / "src/bag_doctor/data/failed_robot_sqlite_demo/failed_robot_sqlite_demo.db3"
META = DB3.parent / "metadata.yaml"


def test_standalone_modes_detect_incident_and_warn():
    for path, expected, metadata in [(MCAP, "ros2_mcap", True), (DB3, "ros2_sqlite_standalone", False)]:
        with stage_upload(path, path.name) as staged:
            result = analyze_bag(staged.path)
            assert staged.kind == expected
            assert staged.metadata_available is metadata
            assert result.incidents[0].start_seconds == pytest.approx(4.9)


def test_zip_sqlite_upload_and_cleanup():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.write(DB3, "robot/failed_robot_sqlite_demo.db3")
        archive.write(META, "robot/metadata.yaml")
    with TestClient(app) as client:
        response = client.post("/api/analyze/upload", files={"file": ("robot.zip", payload.getvalue(), "application/zip")})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["storage_format"] == "ros2_sqlite_directory"
    assert body["incidents"][0]["topic"] == "/scan"


def test_invalid_uploads_are_rejected():
    with pytest.raises(InputValidationError):
        with stage_upload(META, "metadata.yaml"):
            pass
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../../escape.db3", b"bad")
    unsafe = ROOT / ".pytest_cache" / "unsafe.zip"
    unsafe.write_bytes(payload.getvalue())
    with pytest.raises(InputValidationError):
        with stage_upload(unsafe, "unsafe.zip"):
            pass
