"""Bounded GPT investigator over deterministic job evidence."""
from __future__ import annotations
import json, os, re, shutil, subprocess, tempfile
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict
from .jobs import get_job

MODEL = "gpt-5.6"
CODEX_MODEL = "gpt-5.6-terra"
EVIDENCE_RE = re.compile(r"^ev_[0-9a-f]{24}$")

class CodexProviderError(RuntimeError):
    def __init__(self, stage: str, safe_message: str, exit_code: int | None = None):
        super().__init__(safe_message)
        self.stage, self.safe_message, self.exit_code = stage, safe_message, exit_code

def _jsonl_types(stdout: str, *, max_lines: int = 200, max_line_bytes: int = 8192) -> list[str]:
    types: list[str] = []
    for line in stdout.splitlines()[:max_lines]:
        if len(line.encode()) > max_line_bytes:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("type"), str):
            types.append(value["type"])
    return types

class Confidence(str, Enum):
    LOW="low"; MEDIUM="medium"; HIGH="high"
class Observation(BaseModel):
    statement: str = Field(max_length=1000); evidence_ids: list[str] = Field(min_length=1, max_length=10)
class Hypothesis(BaseModel):
    rank: int; hypothesis: str = Field(max_length=1000); confidence: Confidence; reasoning: str = Field(max_length=1500)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    alternative_explanations: list[str] = Field(default_factory=list, max_length=5)
    next_checks: list[str] = Field(default_factory=list, max_length=5)
class ToolTrace(BaseModel):
    tool: str; returned_count: int
class InvestigationResult(BaseModel):
    model: str = MODEL; question: str; summary: str = Field(max_length=2000)
    observations: list[Observation] = Field(default_factory=list, max_length=10)
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    tool_trace: list[ToolTrace] = Field(default_factory=list, max_length=20)

class ListEvidenceArgs(BaseModel):
    offset: int | None = Field(default=0, ge=0)
    limit: int | None = Field(default=20, ge=1, le=25)
    topic: str | None = None
    evidence_type: str | None = None
class GetEvidenceArgs(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=64)
class TopicArgs(BaseModel):
    topic: str = Field(min_length=1, max_length=200)

TOOLS = [{"type":"function","name":"get_analysis_summary","description":"Get deterministic analysis metadata.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True},{"type":"function","name":"list_evidence","description":"List bounded deterministic evidence.","parameters":{"type":"object","properties":{"offset":{"type":["integer","null"]},"limit":{"type":["integer","null"]},"topic":{"type":["string","null"]},"evidence_type":{"type":["string","null"]}},"required":["offset","limit","topic","evidence_type"],"additionalProperties":False},"strict":True},{"type":"function","name":"get_evidence","description":"Retrieve deterministic evidence.","parameters":{"type":"object","properties":{"evidence_id":{"type":"string"}},"required":["evidence_id"],"additionalProperties":False},"strict":True},{"type":"function","name":"get_topic_summary","description":"Get deterministic topic measurements.","parameters":{"type":"object","properties":{"topic":{"type":"string"}},"required":["topic"],"additionalProperties":False},"strict":True}]

def _items(job):
    return [i for t in job.result.topics for i in t.silence_windows] + list(job.result.incidents)

class CodexCliInvestigatorProvider:
    """Read-only Codex CLI provider; output is still validated by the service."""
    def __init__(self, runner=subprocess.run, model: str = CODEX_MODEL):
        self.runner, self.model = runner, model
        self.last_event_types: list[str] = []
    def investigate(self, *, question: str, context: dict) -> str:
        executable = shutil.which("codex")
        if not executable:
            raise CodexProviderError("codex_not_installed", "Codex CLI is unavailable")
        prompt = ("Return exactly one JSON object matching the supplied output schema. "
                  "Use only the bounded deterministic evidence supplied; separate observations and hypotheses, "
                  "cite supplied evidence IDs on every hypothesis, and state that timing measurements alone "
                  "do not establish a physical root cause.\n" +
                  json.dumps({"question": question, "context": context}, separators=(",", ":")))
        with tempfile.TemporaryDirectory(prefix="bag-doctor-codex-") as directory:
            output_path=os.path.join(directory,"result.json")
            schema_path = os.path.join(directory, "result-schema.json")
            # Keep the CLI transport schema deliberately small and self-contained;
            # trusted metadata is added and validated by the investigator service.
            transport_schema = {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "model": {"type": "string"}, "question": {"type": "string"},
                    "summary": {"type": "string"}, "observations": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"statement": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["statement", "evidence_ids"]}},
                    "hypotheses": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"rank": {"type": "integer"}, "hypothesis": {"type": "string"}, "confidence": {"type": "string", "enum": ["low", "medium", "high"]}, "reasoning": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}, "alternative_explanations": {"type": "array", "items": {"type": "string"}}, "next_checks": {"type": "array", "items": {"type": "string"}}}, "required": ["rank", "hypothesis", "confidence", "reasoning", "evidence_ids", "alternative_explanations", "next_checks"]}},
                    "limitations": {"type": "array", "items": {"type": "string"}}, "tool_trace": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"tool": {"type": "string"}, "returned_count": {"type": "integer"}}, "required": ["tool", "returned_count"]}}
                }, "required": ["model", "question", "summary", "observations", "hypotheses", "limitations", "tool_trace"]
            }
            with open(schema_path, "w", encoding="utf-8") as schema_file:
                json.dump(transport_schema, schema_file, separators=(",", ":"))
            args=[executable,"exec","--model",self.model,"--sandbox","read-only","--ephemeral","--ignore-user-config","--ignore-rules","--skip-git-repo-check","--json","--output-schema",schema_path,"-o",output_path,"-"]
            try:
                completed=self.runner(args,input=prompt,text=True,capture_output=True,cwd=directory,timeout=90,check=False,shell=False)
            except subprocess.TimeoutExpired as exc:
                raise CodexProviderError("process_timeout", "Codex investigation timed out") from exc
            self.last_event_types = _jsonl_types(completed.stdout or "")
            if completed.returncode:
                raise CodexProviderError("process_failed", "Codex investigation failed", completed.returncode)
            try:
                if os.path.getsize(output_path) > 20000:
                    raise CodexProviderError("output_too_large", "Codex output exceeded the size limit")
                text=open(output_path, encoding="utf-8").read(20001)
            except FileNotFoundError as exc:
                raise CodexProviderError("output_file_missing", "Codex output file missing") from exc
            if not text.strip(): raise CodexProviderError("output_file_empty", "Codex output file empty")
            try:
                decoder=json.JSONDecoder(); value,end=decoder.raw_decode(text)
                if text[end:].strip(): raise ValueError
            except (json.JSONDecodeError, ValueError) as exc:
                raise CodexProviderError("invalid_json", "Codex output was not one JSON document") from exc
            if not isinstance(value, dict):
                raise CodexProviderError("schema_validation_failed", "Codex output was not an object")
            # These fields are server-controlled; model-generated overrides are ignored.
            value["model"] = self.model
            value["question"] = question
            value["tool_trace"] = []
            return json.dumps(value,separators=(",",":"))

def investigate(job_id: str, question: str, *, client: Any = None, max_tool_calls: int = 6) -> InvestigationResult:
    if not question.strip() or len(question) > 1000: raise ValueError("question must be nonempty and at most 1000 characters")
    if not 1 <= max_tool_calls <= 6: raise ValueError("max_tool_calls must be between 1 and 6")
    job = get_job(job_id)
    if not job: raise LookupError("Unknown job")
    if job.state != "completed" or job.result is None: raise RuntimeError("Analysis is not complete")
    if client is None:
        if not os.getenv("OPENAI_API_KEY") and shutil.which("codex"):
            provider = CodexCliInvestigatorProvider()
            context = {"summary": job.result.summary.model_dump(mode="json"), "topics": [t.model_dump(mode="json") for t in job.result.topics], "evidence": [i.model_dump(mode="json") for i in _items(job)]}
            text = provider.investigate(question=question, context=context)
            try:
                final = InvestigationResult.model_validate_json(text)
            except Exception as exc:
                raise RuntimeError("Invalid investigator result") from exc
            seen = {i.evidence_id for i in _items(job)}
            cited = {x for o in final.observations for x in o.evidence_ids} | {x for h in final.hypotheses for x in h.evidence_ids}
            if not cited or not cited <= seen: raise RuntimeError("Investigator cited unavailable evidence")
            return final
        from openai import OpenAI
        if not os.getenv("OPENAI_API_KEY"): raise RuntimeError("OPENAI_API_KEY is not configured")
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    seen=set(); traces=[]; items=_items(job)
    messages=[{"role":"developer","content":"Use only deterministic timing evidence. State observations separately from hypotheses; never claim physical root causes. Every hypothesis must cite returned evidence IDs."},{"role":"user","content":question}]
    called=0
    while called < max_tool_calls:
        response=client.responses.create(model=MODEL,input=messages,tools=TOOLS,parallel_tool_calls=False)
        output=list(response.output); messages.extend(output)
        calls=[x for x in output if getattr(x,"type",None)=="function_call"]
        if not calls: break
        for call in calls:
            if call.name not in {"get_analysis_summary","list_evidence","get_evidence","get_topic_summary"}: raise RuntimeError("Unknown investigator tool")
            raw_args=json.loads(call.arguments or "{}")
            try:
                args = (ListEvidenceArgs.model_validate(raw_args) if call.name == "list_evidence" else GetEvidenceArgs.model_validate(raw_args) if call.name == "get_evidence" else TopicArgs.model_validate(raw_args) if call.name == "get_topic_summary" else {})
            except Exception as exc:
                raise RuntimeError("Invalid tool arguments") from exc
            if call.name=="list_evidence":
                args=args.model_dump(); limit=args["limit"] or 20; offset=args["offset"] or 0; data=[i for i in items if not args["topic"] or i.topic==args["topic"]]; page=data[offset:offset+limit]
                result={"total_count":len(data),"returned_count":len(page),"items":[i.model_dump(mode="json") for i in page]}
            elif call.name=="get_evidence":
                args=args.model_dump(); result=next((i.model_dump(mode="json") for i in items if i.evidence_id==args["evidence_id"]),{"error":"unknown evidence"})
                if "evidence_id" in result: seen.add(result["evidence_id"])
            elif call.name=="get_topic_summary":
                args=args.model_dump(); t=next((t for t in job.result.topics if t.topic==args["topic"]),None); result=t.model_dump(mode="json") if t else {"error":"unknown topic"}
            else: result={"duration_seconds":job.result.summary.duration_seconds,"total_messages":job.result.summary.total_messages,"topic_count":job.result.summary.topic_count,"incident_count":job.result.incident_count,"returned_incident_count":job.result.returned_incident_count}
            for i in result.get("items",[]) if isinstance(result,dict) else []:
                if i.get("evidence_id"): seen.add(i["evidence_id"])
            traces.append(ToolTrace(tool=call.name,returned_count=len(result.get("items",[])) if isinstance(result,dict) else 1)); messages.append({"type":"function_call_output","call_id":call.call_id,"output":json.dumps(result,separators=(",",":"))}); called+=1
    if called==0: raise RuntimeError("Investigator did not request evidence")
    text=getattr(response,"output_text","")
    try: final=InvestigationResult.model_validate_json(text)
    except Exception as exc: raise RuntimeError("Invalid investigator result") from exc
    cited={x for o in final.observations for x in o.evidence_ids}|{x for h in final.hypotheses for x in h.evidence_ids}
    if not cited or not cited <= seen or any(not EVIDENCE_RE.match(x) for x in cited): raise RuntimeError("Investigator cited unavailable evidence")
    final.tool_trace=traces; return final
