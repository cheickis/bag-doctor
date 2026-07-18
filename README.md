# Bag Doctor

Bag Doctor turns ROS 2 bag recordings into deterministic, evidence-backed failure investigations. This first vertical slice inventories topics and measures timestamp health from a bundled synthetic MCAP recording—without requiring ROS.

## What the demo contains

The 14-second fixture contains valid ROS 2 messages on `/scan` (~10 Hz), `/odom` (~30 Hz), and `/tf` (~10 Hz). `/scan` stops publishing between approximately 5 and 9 seconds; the other topics continue normally.

The analyzer reports topic types, counts, bag duration, median rates, maximum inter-message gaps, and silence windows. It reads raw message timestamps and connection metadata, and does not deserialize payloads during analysis.

## Setup

Install [uv](https://docs.astral.sh/uv/), then from the repository root run:

```bash
uv sync
```

`uv` reads `.python-version`, installs Python 3.12 if necessary, and creates `.venv` with all runtime and test dependencies.

## Run

```bash
uv run uvicorn bag_doctor.main:app --reload
```

Open <http://127.0.0.1:8000> and select **Analyze Failed Robot Demo**. The structured endpoint is available directly at <http://127.0.0.1:8000/api/analyze/demo>, and FastAPI's generated API documentation is at <http://127.0.0.1:8000/docs>.

## Test

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest
```

Disabling third-party pytest plugin auto-loading keeps the test environment independent from any globally sourced ROS installation. The project's own tests do not require external pytest plugins.

## Regenerate the bundled bag

The generated MCAP fixture and its rosbag2 metadata are committed under `src/bag_doctor/data/failed_robot_demo`. To reproduce it deterministically:

```bash
uv run python -m bag_doctor.demo
```

Then rerun the tests. Generation uses `rosbags` message definitions and produces valid `sensor_msgs/msg/LaserScan`, `nav_msgs/msg/Odometry`, and `tf2_msgs/msg/TFMessage` payloads.

## Project layout

```text
src/bag_doctor/
├── analyzer.py       # Timestamp-only deterministic measurements
├── demo.py           # Synthetic MCAP generator
├── main.py           # FastAPI routes
├── schemas.py        # Pydantic response models
├── data/             # Bundled generated rosbag2 MCAP
└── web/index.html    # Minimal browser interface
tests/                # Analyzer and API tests
```

This milestone intentionally contains no LLM integration, authentication, storage service, live ROS connection, RViz, or point-cloud visualization.
