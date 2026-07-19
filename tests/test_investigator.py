import json
from types import SimpleNamespace
import pytest

from bag_doctor.analyzer import analyze_bag
from bag_doctor.investigator import investigate, MODEL
from bag_doctor.jobs import Job, _jobs, _lock
from bag_doctor.main import DEMO_BAG

class FakeResponses:
    def __init__(self, outputs): self.outputs=iter(outputs); self.calls=[]
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.outputs)
class FakeClient:
    def __init__(self, outputs): self.responses=FakeResponses(outputs)
def call(name, args, call_id="c1"):
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=call_id)
def reasoning(): return SimpleNamespace(type="reasoning", id="r1", summary=[])
def final(eid):
    return SimpleNamespace(output=[], output_text=json.dumps({"model":MODEL,"question":"q","summary":"s","observations":[],"hypotheses":[{"rank":1,"hypothesis":"possible","confidence":"low","reasoning":"timing","evidence_ids":[eid]}],"limitations":[],"tool_trace":[]}))
def job():
    j=Job("investigator-test", DEMO_BAG, state="completed", result=analyze_bag(DEMO_BAG));
    with _lock: _jobs[j.id]=j
    return j

def test_tool_loop_model_call_ids_and_reasoning():
    j=job(); eid=j.result.incidents[0].evidence_id
    fake=FakeClient([SimpleNamespace(output=[reasoning(),call("list_evidence",{"offset":0,"limit":5,"topic":None,"evidence_type":None})]), final(eid)])
    result=investigate(j.id,"q",client=fake)
    assert result.model == "gpt-5.6"
    assert fake.responses.calls[0]["model"] == "gpt-5.6"
    assert fake.responses.calls[0]["parallel_tool_calls"] is False
    assert fake.responses.calls[1]["input"][2].type == "reasoning"
    output=[x for x in fake.responses.calls[1]["input"] if isinstance(x,dict) and x.get("type")=="function_call_output"]
    assert output[0]["call_id"] == "c1"

def test_invalid_and_missing_citations_rejected():
    j=job(); fake=FakeClient([SimpleNamespace(output=[call("list_evidence",{"offset":0,"limit":1,"topic":None,"evidence_type":None})]), final("ev_000000000000000000000000")])
    with pytest.raises(RuntimeError, match="unavailable"):
        investigate(j.id,"q",client=fake)

def test_caps_and_unknown_tools():
    j=job(); fake=FakeClient([SimpleNamespace(output=[call("wat",{})])])
    with pytest.raises(RuntimeError, match="Unknown"):
        investigate(j.id,"q",client=fake)
    with pytest.raises(ValueError): investigate(j.id,"q",client=fake,max_tool_calls=7)

def test_incomplete_and_missing_key_rejected():
    j=Job("incomplete", DEMO_BAG, state="running")
    with _lock: _jobs[j.id]=j
    with pytest.raises(RuntimeError, match="complete"): investigate(j.id,"q",client=FakeClient([]))
