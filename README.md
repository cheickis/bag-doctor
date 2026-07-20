# Bag Doctor

Bag Doctor is an evidence-driven failure investigator for ROS 2 bag recordings. It performs deterministic, timestamp-only analysis first, ranks timing incidents, assigns stable evidence IDs, and gives GPT-5.6 only bounded evidence context from the completed analysis. The result is a structured set of evidence-cited hypotheses—not a claim that a physical cause has been proven.

> **Safety boundary:** Timing measurements alone do not establish a physical root cause.

## Judge quick start

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), a modern browser, and a ChatGPT-authenticated Codex CLI session for the GPT-5.6 Terra step. The project is currently verified on Linux; no other operating-system support is claimed.

From the repository root:

```bash
uv sync
uv run uvicorn bag_doctor.main:app
```

Then:

1. Open <http://127.0.0.1:8000> in a local browser.
2. Click **Run bundled demo**.
3. Inspect the deterministic summary, ranked timing incidents, and bounded evidence records.
4. Click **Investigate with GPT-5.6**.
5. Click an evidence citation in a hypothesis to navigate back to its deterministic evidence card.

The bundled demo is the fastest judge and video workflow. It is synthetic and intentionally contains useful failure evidence: valid ROS 2 messages on `/scan`, `/odom`, and `/tf`, with `/scan` silent for roughly four seconds while the other topics continue.

## What happens under the hood

```text
ROS 2 bag
  → bounded-memory deterministic analysis
  → ranked timing incidents
  → stable evidence IDs
  → bounded evidence context
  → GPT-5.6
  → structured, evidence-cited hypotheses
```

The analyzer reads message timestamps and connection metadata without deserializing message payloads. It reports topic inventory, bag duration, message counts, median rates, maximum gaps, timing classifications, and bounded silence-window evidence. Bag Doctor does not prove root causes, repair bags, create corrected binary bags, inspect malformed message payloads, or guarantee repair commands. Raw message telemetry is not sent to GPT-5.6.

## GPT-5.6 Investigator

### Primary judge path: Codex CLI

The application uses the ChatGPT-authenticated Codex CLI and model `gpt-5.6-terra`. Authenticate before launching Bag Doctor:

```bash
codex login
codex login status
```

No `OPENAI_API_KEY` is required for this path. If one is already set, unset it when demonstrating the primary Codex CLI provider because the current provider selection uses the Responses API when that variable is present.

The server completes deterministic analysis before invoking GPT-5.6. It then makes one bounded, structured Codex invocation containing only the analysis summary, topic measurements, and bounded evidence—not raw bag telemetry. The server controls model/question metadata and validates the structured response and every cited ID against evidence owned by the completed process-local job. The prompt requires the timing-only physical-root-cause limitation; the bundled validation command checks the structured result and evidence citations:

```bash
uv run python scripts/smoke_test_codex_investigator.py
```

### Optional provider: OpenAI Responses API

The OpenAI Responses API is an optional validation path, not part of the primary judge workflow. It requires an independently billed API account and `OPENAI_API_KEY`, and may incur charges:

```bash
# Load OPENAI_API_KEY securely first; do not paste it into shell history.
uv run python scripts/smoke_test_investigator.py
```

This provider uses bounded evidence tools, validates cited evidence ownership, and its smoke test validates that the response includes the timing-only safety limitation. Exit code `0` means validation passed, `1` means the request or result failed safely, and `2` means provider configuration is missing.

## Example judge walkthrough

This takes only a few minutes:

1. Launch the server and open the local URL.
2. Run the bundled demo.
3. Review the recording summary and topic classifications.
4. Open the ranked incidents and bounded evidence.
5. Run the GPT-5.6 Investigator.
6. Click a cited evidence ID to return to that evidence card.
7. Open **Report** in the navigation and use **Print report** or browser print preview.

## Supported inputs

### Browser Upload

The browser accepts:

- a standalone `.mcap`;
- a standalone `.db3`;
- a `.zip` containing one complete split SQLite ROS 2 bag: `metadata.yaml` and every `.db3` segment.

A standalone `.db3` does not require separately selecting `metadata.yaml`. The backend creates a temporary staging workspace and reads the necessary topic metadata directly from the SQLite bag tables. Browser uploads are limited to 512 MiB and temporary files are removed after analysis.

For any split bag, the archive must keep `metadata.yaml` together with every segment. The current ZIP validator supports `.db3` segments; an MCAP-only split ZIP is not currently accepted, so use a standalone `.mcap` or the Local path workflow for a complete MCAP directory. Archives reject traversal paths, symlinks, malformed content, incomplete SQLite bags, and multiple unrelated bag roots.

**Current limitation:** direct Upload returns an analysis result but does not register a completed job ID. GPT-5.6 investigation is therefore unavailable for direct Upload results.

### Local path

Local path analyzes a complete bag directory in place and is the recommended workflow for large recordings. The directory should contain `metadata.yaml` and all `.db3` or `.mcap` segments, and the server process must have filesystem access to its absolute path. Enter that path in the dashboard, or use:

```bash
curl -X POST http://127.0.0.1:8000/api/analyze/local \
  -H 'content-type: application/json' \
  -d '{"path":"/absolute/path/to/bag-directory"}'
```

The API returns a job ID for status, evidence, cancellation, and investigation. A real approximately 37.5 GiB ROS 2 bag containing 744,684 messages was successfully analyzed through this Local workflow. It produced six leading-boundary timing findings, and six bounded evidence records enabled investigation with GPT-5.6 Terra. That run did **not** validate the unrelated synthetic 7.9-to-13.9-second trailing-boundary case.

### Bundled Demo

The committed synthetic MCAP fixture lives under `src/bag_doctor/data/failed_robot_demo/`. It requires no external ROS installation and creates a registered completed job, so the full deterministic-analysis-to-investigator workflow is available.

To regenerate it during development:

```bash
uv run python -m bag_doctor.demo
```

## Architecture and safeguards

- A temporary SQLite workspace stores timestamp gaps on disk so analysis memory stays bounded rather than retaining decoded messages.
- Results cap per-topic silence windows and globally ranked incidents; evidence passed to GPT-5.6 is bounded.
- Evidence IDs are deterministic hashes of the bag path and timing record, and citations must belong to the requested job.
- Jobs, cached results, and evidence live in a process-local registry. Restarting the server ends their lifetime.
- Local analysis supports cooperative cancellation at safe checkpoints; cancelled partial results are not published.
- Progress, elapsed time, and ETA come from processed and known total message counts. Unknown totals do not fabricate percentages or ETAs.
- Known event-driven topics such as `/parameter_events` and `/rosout` are excluded from inferred periodic silence detection.
- Silence detection covers internal gaps and leading/trailing recording boundaries.
- Analyzer callers can provide per-topic classifications, expected rates, and timing thresholds. The current browser UI does not expose those advanced settings.

## API summary

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/` | Committed React application |
| `GET` | `/api/analyze/demo` | Direct deterministic demo result |
| `GET` | `/api/analyze/demo/job` | Analyze demo and register a completed job |
| `POST` | `/api/analyze/upload` | Analyze a supported browser upload directly |
| `POST` | `/api/analyze/local` | Start a process-local analysis job |
| `GET` | `/api/analyze/jobs/{job_id}` | Read job progress and completed result |
| `GET` | `/api/analyze/jobs/{job_id}/events` | Stream progress and terminal state with SSE |
| `POST` | `/api/analyze/jobs/{job_id}/cancel` | Request cooperative cancellation |
| `GET` | `/api/analyze/jobs/{job_id}/evidence` | Page/filter bounded job evidence |
| `GET` | `/api/analyze/jobs/{job_id}/evidence/{evidence_id}` | Read one job-owned evidence record |
| `POST` | `/api/analyze/jobs/{job_id}/investigate` | Run the bounded GPT-5.6 investigator |
| `GET` | `/health` | Process health check |

Interactive FastAPI documentation is available at <http://127.0.0.1:8000/docs>.

## Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest
```

Disabling third-party pytest plugin auto-loading keeps tests independent from globally sourced ROS installations. Tests do not require a live ROS installation or paid API call.

## Frontend assets and optional rebuild

The active React source is under `frontend/`, and committed production assets are included under `src/bag_doctor/web/dist/`; `GET /` serves the production React entry, so judges do not need Node.js to install or run Bag Doctor. The abandoned vanilla frontend entry has been removed.

Frontend rebuilding is optional. No Node version is declared by this project, so use a Node/npm environment compatible with the locked dependencies:

```bash
cd frontend
npm ci
npm run build
```

## How Codex supported development

Codex was used as a development collaborator to implement and review narrow milestones, add tests, inspect diffs, validate frontend and backend behavior, verify analysis against a real ROS 2 bag, and maintain frequent, narrowly scoped commits. This does not mean Codex independently built the entire project. A Codex `/feedback` Session ID is included in the Devpost submission for reviewer context.

## Troubleshooting

**Codex CLI is not authenticated**

Run `codex login`, confirm with `codex login status`, and restart the investigation. The primary path uses ChatGPT authentication, not `OPENAI_API_KEY`.

**Port 8000 is already in use**

Launch on another port, for example `uv run uvicorn bag_doctor.main:app --port 8001`, then open <http://127.0.0.1:8001>.

**No bounded evidence**

No bounded evidence is available for this recording. GPT-5.6 only investigates evidence produced by deterministic analysis. Zero bounded evidence is not proof that a bag is healthy; it only means no finding met the implemented classification, threshold, and result-bound rules.

**Direct Upload investigator unavailable**

This is expected: direct Upload results do not currently create registered completed job IDs. Use the bundled Demo or Local path workflow for GPT-5.6 investigation.

**Incomplete split bag ZIP**

Include one `metadata.yaml` and every `.db3` segment under a single bag root. Split MCAP ZIPs are not currently accepted; use a standalone `.mcap` or Local path.

**Local path inaccessible**

Use an existing absolute bag path. Ensure the server process can read the directory, `metadata.yaml`, and every segment.

**A job or evidence disappeared after restart**

Jobs and evidence are process-local and intentionally ephemeral. Run the Demo or Local analysis again after restarting the server.

## License

[MIT](LICENSE)
