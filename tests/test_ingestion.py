from pathlib import Path
import io, zipfile
import sqlite3
from mcap.writer import Writer

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
    for path, expected, metadata in [(MCAP, "ros2_mcap", False), (DB3, "ros2_sqlite_standalone", False)]:
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


def test_invalid_uploads_are_rejected(tmp_path):
    with pytest.raises(InputValidationError):
        with stage_upload(META, "metadata.yaml"):
            pass
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../../escape.db3", b"bad")
    unsafe = tmp_path / "unsafe.zip"
    unsafe.write_bytes(payload.getvalue())
    with pytest.raises(InputValidationError):
        with stage_upload(unsafe, "unsafe.zip"):
            pass


def test_fresh_standalone_mcap_upload(tmp_path):
    recording = tmp_path / "unrelated.mcap"
    with recording.open("wb") as stream:
        writer = Writer(stream); writer.start()
        schema = writer.register_schema("custom/ImuTest", "jsonschema", b"{}")
        channel = writer.register_channel("/imu_test", "custom/ImuTest", schema_id=schema)
        for index in range(4): writer.add_message(channel, log_time=1_000_000_000 * (index + 1), publish_time=0, data=b"{}")
        writer.finish()
    with TestClient(app) as client:
        response = client.post("/api/analyze/upload", files={"file": (recording.name, recording.read_bytes(), "application/octet-stream")})
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["storage_format"] == "ros2_mcap"
    assert summary["total_messages"] == 4
    assert summary["duration_seconds"] == 3.0
    assert [topic["topic"] for topic in response.json()["topics"]] == ["/imu_test"]


def test_fresh_standalone_sqlite_upload(tmp_path):
    recording = tmp_path / "unrelated.db3"
    db = sqlite3.connect(recording)
    db.executescript("CREATE TABLE topics(id INTEGER PRIMARY KEY, name TEXT, type TEXT, serialization_format TEXT, offered_qos_profiles TEXT); CREATE TABLE messages(id INTEGER PRIMARY KEY, topic_id INTEGER, timestamp INTEGER, data BLOB); INSERT INTO topics VALUES (1, '/imu_test', 'custom/ImuTest', 'cdr', '');")
    db.executemany("INSERT INTO messages(topic_id,timestamp,data) VALUES (1,?,?)", [(n * 1_000_000_000, b'x') for n in range(1, 5)])
    db.commit(); db.close()
    with TestClient(app) as client:
        response = client.post("/api/analyze/upload", files={"file": (recording.name, recording.read_bytes(), "application/octet-stream")})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["storage_format"] == "ros2_sqlite_standalone"
    assert body["summary"]["total_messages"] == 4
    assert body["summary"]["duration_seconds"] == 3.0
    assert [topic["topic"] for topic in body["topics"]] == ["/imu_test"]


def test_invalid_sqlite_upload_is_400(tmp_path):
    recording = tmp_path / "ordinary.db3"
    sqlite3.connect(recording).close()
    with TestClient(app) as client:
        response = client.post("/api/analyze/upload", files={"file": (recording.name, recording.read_bytes(), "application/octet-stream")})
    assert response.status_code == 400
    assert "ROS 2 bag" in response.json()["detail"]


def test_sqlite_missing_topic_column_is_readable_400(tmp_path):
    recording = tmp_path / "missing-topic-type.db3"
    db = sqlite3.connect(recording)
    db.executescript("CREATE TABLE topics(id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE messages(topic_id INTEGER, timestamp INTEGER, data BLOB);")
    db.commit(); db.close()
    with TestClient(app) as client:
        response = client.post("/api/analyze/upload", files={"file": (recording.name, recording.read_bytes(), "application/octet-stream")})
    assert response.status_code == 400
    assert "topics" in response.json()["detail"]
    assert "type" in response.json()["detail"]
    assert "Traceback" not in response.text


def test_sqlite_missing_message_column_is_readable_400(tmp_path):
    recording = tmp_path / "missing-message-timestamp.db3"
    db = sqlite3.connect(recording)
    db.executescript("CREATE TABLE topics(id INTEGER PRIMARY KEY, name TEXT, type TEXT); CREATE TABLE messages(topic_id INTEGER, data BLOB);")
    db.commit(); db.close()
    with TestClient(app) as client:
        response = client.post("/api/analyze/upload", files={"file": (recording.name, recording.read_bytes(), "application/octet-stream")})
    assert response.status_code == 400
    assert "messages" in response.json()["detail"]
    assert "timestamp" in response.json()["detail"]
    assert "Traceback" not in response.text
