"""Optional paid Responses API smoke validation over bounded Demo evidence."""
from __future__ import annotations

import os
import re
import secrets
import sys
from collections.abc import Callable, Mapping
from typing import Any, TextIO

from bag_doctor.analyzer import analyze_bag
from bag_doctor.investigator import MODEL, investigate
from bag_doctor.jobs import Job, _jobs, _lock
from bag_doctor.main import DEMO_BAG

QUESTION = "What most likely happened during the largest timing disruption?"
EVIDENCE_ID = re.compile(r"^ev_[0-9a-f]{24}$")
PROVIDER = "responses_api"


class SmokeValidationError(RuntimeError):
    """A safe, user-facing validation failure."""


def bounded_evidence_ids(analysis: Any) -> set[str]:
    ids = {item.evidence_id for topic in analysis.topics for item in topic.silence_windows}
    ids.update(item.evidence_id for item in analysis.incidents)
    return {evidence_id for evidence_id in ids if evidence_id is not None}


def validate_investigation(investigation: Any, available_evidence: set[str]) -> set[str]:
    if getattr(investigation, "model", None) != MODEL:
        raise SmokeValidationError("unexpected model metadata")
    hypotheses = getattr(investigation, "hypotheses", None)
    if not isinstance(hypotheses, list) or not hypotheses:
        raise SmokeValidationError("no valid hypotheses returned")
    observations = getattr(investigation, "observations", None)
    if not isinstance(observations, list):
        raise SmokeValidationError("malformed observations")
    cited = {evidence_id for observation in observations for evidence_id in observation.evidence_ids}
    for hypothesis in hypotheses:
        if not hypothesis.evidence_ids:
            raise SmokeValidationError("hypothesis has no evidence citation")
        cited.update(hypothesis.evidence_ids)
    if not cited:
        raise SmokeValidationError("no evidence cited")
    if any(not EVIDENCE_ID.fullmatch(evidence_id) or evidence_id not in available_evidence for evidence_id in cited):
        raise SmokeValidationError("invalid or unavailable evidence citation")
    limitations = getattr(investigation, "limitations", None)
    if not isinstance(limitations, list) or not any(
        "timing measurements alone" in text.lower() and "physical root cause" in text.lower()
        for text in limitations if isinstance(text, str)
    ):
        raise SmokeValidationError("timing-only limitation is absent")
    if not getattr(investigation, "tool_trace", None):
        raise SmokeValidationError("no bounded evidence tool call")
    return cited


def main(
    *,
    environment: Mapping[str, str] | None = None,
    analyzer: Callable[[Any], Any] = analyze_bag,
    investigator: Callable[..., Any] = investigate,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    environment = os.environ if environment is None else environment
    if not environment.get("OPENAI_API_KEY"):
        print("SMOKE TEST ERROR: Responses API configuration is missing", file=stderr)
        return 2
    job_id = f"responses-smoke-{secrets.token_hex(8)}"
    try:
        analysis = analyzer(DEMO_BAG)
        job = Job(job_id, DEMO_BAG, state="completed", stage="completed", result=analysis)
        with _lock:
            _jobs[job.id] = job
        investigation = investigator(job.id, QUESTION, max_tool_calls=6)
        cited = validate_investigation(investigation, bounded_evidence_ids(analysis))
        print(f"PROVIDER {PROVIDER}", file=stdout)
        print(f"MODEL {investigation.model}", file=stdout)
        print(f"TOOLS CALLED {len(investigation.tool_trace)}", file=stdout)
        print(f"CITED EVIDENCE {len(cited)}", file=stdout)
        print(f"HYPOTHESES {len(investigation.hypotheses)}", file=stdout)
        print("SMOKE TEST RESULT PASS", file=stdout)
        return 0
    except SmokeValidationError as exc:
        print(f"SMOKE TEST ERROR: {exc}", file=stderr)
        return 1
    except Exception:
        print("SMOKE TEST ERROR: Responses API request or validation failed", file=stderr)
        return 1
    finally:
        with _lock:
            _jobs.pop(job_id, None)


if __name__ == "__main__":
    raise SystemExit(main())
