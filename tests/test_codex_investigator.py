from types import SimpleNamespace
import pytest
from bag_doctor.investigator import CodexCliInvestigatorProvider

def test_codex_command_is_sandboxed_and_server_controlled(tmp_path):
    seen={}
    def runner(args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        out = args[args.index('-o') + 1]
        with open(out, 'w', encoding='utf-8') as f:
            f.write('{"status":"ok"}')
        return SimpleNamespace(returncode=0, stdout='{"type":"thread.started"}\n{"type":"turn.completed"}', stderr='secret')
    p=CodexCliInvestigatorProvider(runner=runner, model='gpt-5.6-terra')
    import bag_doctor.investigator as mod
    old=mod.shutil.which; mod.shutil.which=lambda _: '/usr/bin/codex'
    try: p.investigate(question='x; --dangerously-bypass-approvals-and-sandbox', context={'evidence':[]})
    finally: mod.shutil.which=old
    assert seen['args'][:3]==['/usr/bin/codex','exec','--model']
    assert 'gpt-5.6-terra' in seen['args']; assert '--sandbox' in seen['args'] and 'read-only' in seen['args']
    assert '--json' in seen['args'] and '--output-schema' in seen['args']
    assert seen['kwargs']['shell'] is False and seen['kwargs']['timeout'] == 90
    assert seen['kwargs']['cwd'] != '.'

def test_missing_codex_is_controlled(monkeypatch):
    import bag_doctor.investigator as mod
    monkeypatch.setattr(mod.shutil, 'which', lambda _: None)
    with pytest.raises(RuntimeError, match='unavailable'):
        CodexCliInvestigatorProvider().investigate(question='x', context={})

def test_nonzero_codex_is_sanitized(monkeypatch):
    import bag_doctor.investigator as mod
    monkeypatch.setattr(mod.shutil, 'which', lambda _: '/codex')
    def runner(*a, **k): return SimpleNamespace(returncode=1, stdout='', stderr='token=secret')
    with pytest.raises(RuntimeError, match='failed'):
        CodexCliInvestigatorProvider(runner=runner).investigate(question='x', context={})
