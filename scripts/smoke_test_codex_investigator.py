import os, subprocess, sys, re
from bag_doctor.analyzer import analyze_bag
from bag_doctor.investigator import CodexCliInvestigatorProvider, InvestigationResult
from bag_doctor.jobs import Job, _jobs, _lock
from bag_doctor.main import DEMO_BAG

def main():
    if not os.getenv('CODEX_HOME') and subprocess.run(['codex','login','status'],capture_output=True,text=True).returncode:
        print('Codex authentication unavailable', file=sys.stderr); return 2
    result=analyze_bag(DEMO_BAG); job=Job('codex-smoke',DEMO_BAG,state='completed',result=result)
    with _lock: _jobs[job.id]=job
    try:
        text=CodexCliInvestigatorProvider().investigate(question='What most likely happened during the largest timing disruption?',context={'summary':result.summary.model_dump(mode='json'),'evidence':[i.model_dump(mode='json') for i in result.incidents]})
        parsed=InvestigationResult.model_validate_json(text)
        allowed={i.evidence_id for i in result.incidents}
        cited={x for o in parsed.observations for x in o.evidence_ids}|{x for h in parsed.hypotheses for x in h.evidence_ids}
        if parsed.model != 'gpt-5.6-terra' or not cited or not cited <= allowed or any(not re.fullmatch(r'ev_[0-9a-f]{24}', x) for x in cited):
            print('FAILURE STAGE citation_validation_failed', file=sys.stderr); return 1
        print('PROVIDER\ncodex_cli\nMODEL\n'+parsed.model+'\nQUESTION\nWhat most likely happened during the largest timing disruption?')
        print('CITED EVIDENCE IDS\n'+' '.join(sorted(cited))); print('SUMMARY\n'+parsed.summary)
        print('OBSERVATIONS\n'+str(len(parsed.observations))); print('HYPOTHESES\n'+str(len(parsed.hypotheses))); print('LIMITATIONS\n'+' | '.join(parsed.limitations)); print('SMOKE TEST RESULT\nPASS'); return 0
    except Exception as exc:
        print('FAILURE STAGE investigator_failed\nSAFE MESSAGE\n'+type(exc).__name__, file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
