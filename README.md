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

## Optional live investigator validation

The primary hackathon demonstration path is the ChatGPT-authenticated Codex CLI with GPT-5.6 Terra:

```bash
uv run python scripts/smoke_test_codex_investigator.py
```

This path does not use `OPENAI_API_KEY` and does not require paid OpenAI API credits. The smaller `scripts/probe_codex_structured_output.py` checks only the Codex structured-output transport.

The Responses API smoke test is an optional provider validation and is not required for judges or for the main project workflow:

```bash
# Load OPENAI_API_KEY from your secret manager or a secure shell prompt first.
uv run python scripts/smoke_test_investigator.py
```

It requires an OpenAI API account with available billing or credits and may incur API charges. The script analyzes the bundled deterministic Demo, exercises the existing bounded-evidence investigator, and validates evidence ownership and the timing-only physical-root-cause limitation. It does not store or print API responses, prompts, transcripts, credentials, authentication details, or provider errors.

Exit status `0` means validation passed, `1` means the request or returned result failed safely, and `2` means Responses API configuration is missing. Do not place an API key directly in shell history.

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

## ROS 2 uploads

ROS 1 commonly uses `.bag`. ROS 2 commonly uses an `.mcap` file or a bag directory containing `.db3` files plus `metadata.yaml`. The upload endpoint supports:

- standalone `.mcap`
- `.zip` archives containing one ROS 2 bag root with `metadata.yaml` and one or more `.db3` files (split bags supported)
- standalone `.db3` as a convenience mode; a warning explains that metadata was not supplied

Recommended ZIP structure:

```text
my-bag.zip
└── my-bag/
    ├── metadata.yaml
    ├── my-bag_0.db3
    └── my-bag_1.db3
```

Uploads are limited to 512 MiB. Archives reject traversal paths, symlinks, malformed content, missing metadata, missing database files, and ambiguous unrelated bag roots. Temporary staging files are removed after every analysis.

## Large local bags (recommended)

For 40 GB–250+ GB recordings, use local in-place analysis. Large bags are never uploaded or copied:

```bash
curl -X POST http://127.0.0.1:8000/api/analyze/local \
  -H 'content-type: application/json' \
  -d '{"path":"/absolute/path/to/bag-directory"}'
uv run bag-doctor --bag /absolute/path/to/bag-directory
```

The API returns a job ID. Poll `/api/analyze/jobs/{job_id}`, cancel with `POST /api/analyze/jobs/{job_id}/cancel`, or subscribe to `/api/analyze/jobs/{job_id}/events` using Server-Sent Events. Local analysis opens source files read-only and keeps the 512 MiB upload convenience limit unchanged. No bag bytes leave the machine. Runtime and memory depend on storage indexes, message count, and filesystem throughput; timestamp analysis does not deserialize message payloads.
