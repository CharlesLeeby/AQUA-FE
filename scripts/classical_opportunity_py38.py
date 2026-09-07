#!/usr/bin/env python3
"""Registered Python 3.8 syntax compatibility; frozen metric source stays intact."""
import hashlib
import json
from pathlib import Path
import sys
import types

ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'papers/frontend_classical_opportunity_expansion_v1'

def load_analysis():
    original=ROOT/'scripts/analyze_classical_opportunity_expansion.py'
    code=original.read_text()
    old="armstats.append({k:v for k,v in case.items() if k.startswith(arm+'_')}|dict(window_id=w['window_id'],arm=arm))"
    new="armstats.append(dict({k:v for k,v in case.items() if k.startswith(arm+'_')},window_id=w['window_id'],arm=arm))"
    assert code.count(old)==1
    code=code.replace(old,new)
    lock=json.loads((PAPER/'python38_compatibility_lock.json').read_text())
    assert hashlib.sha256(original.read_bytes()).hexdigest()==lock['original_analysis_sha256']
    assert hashlib.sha256(code.encode()).hexdigest()==lock['compatible_analysis_sha256']
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==lock['adapter_sha256']
    module=types.ModuleType('analyze_classical_opportunity_expansion')
    module.__file__=str(original)
    sys.modules[module.__name__]=module
    exec(compile(code,str(original)+'[python38-dict-construction]','exec'),module.__dict__)
    return module

if __name__=='__main__':
    analysis=load_analysis()
    if '--analyze-only' in sys.argv:analysis.analyze()
    else:
        import execute_classical_opportunity_batch as batch
        batch.main()
