"""Bounded GPT investigator over deterministic job evidence."""
from __future__ import annotations
import json, os, re
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict
from .jobs import get_job

MODEL = "gpt-5.6"
EVIDENCE_RE = re.compile(r"^ev_[0-9a-f]{24}$")

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

def investigate(job_id: str, question: str, *, client: Any = None, max_tool_calls: int = 6) -> InvestigationResult:
    if not question.strip() or len(question) > 1000: raise ValueError("question must be nonempty and at most 1000 characters")
    if not 1 <= max_tool_calls <= 6: raise ValueError("max_tool_calls must be between 1 and 6")
    job = get_job(job_id)
    if not job: raise LookupError("Unknown job")
    if job.state != "completed" or job.result is None: raise RuntimeError("Analysis is not complete")
    if client is None:
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
