"""Small local Codex structured-output control probe; prints sanitized status only."""
import json, os, shutil, subprocess, sys, tempfile

def main():
    exe=shutil.which('codex')
    if not exe: print('FAILURE STAGE codex_not_installed'); return 1
    schema={"type":"object","properties":{"status":{"type":"string","enum":["ok"]},"model":{"type":"string"}},"required":["status","model"],"additionalProperties":False}
    with tempfile.TemporaryDirectory(prefix='bag-doctor-probe-') as d:
        sp=os.path.join(d,'schema.json'); op=os.path.join(d,'result.json'); open(sp,'w').write(json.dumps(schema))
        args=[exe,'exec','--model','gpt-5.6-terra','--sandbox','read-only','--ephemeral','--ignore-user-config','--ignore-rules','--skip-git-repo-check','--json','--output-schema',sp,'-o',op,'-']
        p=subprocess.run(args,input='Return exactly {"status":"ok","model":"gpt-5.6-terra"}',text=True,capture_output=True,cwd=d,timeout=90,shell=False)
        if p.returncode or not os.path.exists(op): print('FAILURE STAGE process_failed'); return 1
        try: value=json.loads(open(op).read())
        except Exception: print('FAILURE STAGE invalid_json'); return 1
        print('CONTROL PROBE PASS', value.get('model')); return 0
if __name__=='__main__': raise SystemExit(main())
