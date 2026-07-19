import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

from bag_doctor.analyzer import analyze_bag
from bag_doctor.investigator import MODEL
from bag_doctor.main import DEMO_BAG

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "smoke_test_investigator.py"


def load_script(name="responses_smoke"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load_script()


def result(evidence_ids=None, limitations=None):
    evidence_ids = evidence_ids if evidence_ids is not None else []
    return SimpleNamespace(
        model=MODEL,
        observations=[],
        hypotheses=[SimpleNamespace(evidence_ids=evidence_ids)],
        limitations=limitations if limitations is not None else [
            "Timing measurements alone do not establish a physical root cause."
        ],
        tool_trace=[SimpleNamespace(tool="list_evidence", returned_count=1)],
    )


def run_with(investigation):
    analysis = analyze_bag(DEMO_BAG)
    output, error = io.StringIO(), io.StringIO()
    code = smoke.main(
        environment={"OPENAI_API_KEY": "test-only-placeholder"},
        analyzer=lambda _path: analysis,
        investigator=lambda *_args, **_kwargs: investigation,
        stdout=output,
        stderr=error,
    )
    return code, output.getvalue(), error.getvalue(), analysis


def test_import_has_no_live_side_effects(monkeypatch):
    calls = []
    monkeypatch.setattr("bag_doctor.analyzer.analyze_bag", lambda *_args: calls.append("analysis"))
    monkeypatch.setattr("bag_doctor.investigator.investigate", lambda *_args: calls.append("network"))
    load_script("responses_smoke_import_check")
    assert calls == []


def test_missing_configuration_is_controlled_without_work(monkeypatch):
    output, error = io.StringIO(), io.StringIO()
    code = smoke.main(
        environment={}, analyzer=lambda _path: (_ for _ in ()).throw(AssertionError("must not run")),
        stdout=output, stderr=error,
    )
    assert code == 2
    assert output.getvalue() == ""
    assert "configuration is missing" in error.getvalue()


def test_valid_responses_investigation_passes_without_raw_payload_output():
    analysis = analyze_bag(DEMO_BAG)
    evidence_id = analysis.incidents[0].evidence_id
    code, output, error, _ = run_with(result([evidence_id]))
    assert code == 0 and error == ""
    assert "PROVIDER responses_api" in output
    assert "SMOKE TEST RESULT PASS" in output
    assert QUESTION_NOT_PRINTED not in output
    assert "Timing measurements alone" not in output


QUESTION_NOT_PRINTED = smoke.QUESTION


def test_unknown_or_missing_evidence_citations_fail():
    code, _, error, _ = run_with(result(["ev_000000000000000000000000"]))
    assert code == 1 and "invalid or unavailable evidence citation" in error
    code, _, error, _ = run_with(result([]))
    assert code == 1 and "hypothesis has no evidence citation" in error


def test_missing_timing_only_limitation_fails():
    analysis = analyze_bag(DEMO_BAG)
    code, _, error, _ = run_with(result([analysis.incidents[0].evidence_id], ["More checks are needed."]))
    assert code == 1 and "timing-only limitation is absent" in error


def test_malformed_result_and_provider_exception_are_sanitized():
    code, output, error, _ = run_with(SimpleNamespace(model=MODEL, hypotheses=None))
    assert code == 1 and output == "" and "no valid hypotheses" in error

    secret = "authorization bearer private-provider-detail"
    analysis = analyze_bag(DEMO_BAG)
    output, error = io.StringIO(), io.StringIO()
    code = smoke.main(
        environment={"OPENAI_API_KEY": "test-only-placeholder"},
        analyzer=lambda _path: analysis,
        investigator=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
        stdout=output, stderr=error,
    )
    assert code == 1 and output.getvalue() == ""
    assert "request or validation failed" in error.getvalue()
    assert secret not in error.getvalue()
    assert "test-only-placeholder" not in error.getvalue()


def test_codex_smoke_script_remains_a_separate_file():
    codex_script = Path(__file__).parents[1] / "scripts" / "smoke_test_codex_investigator.py"
    assert codex_script.is_file()
    assert "CodexCliInvestigatorProvider" in codex_script.read_text(encoding="utf-8")
