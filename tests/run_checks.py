"""Run isolated regression tests; no production database or paid model calls."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

root=Path(__file__).resolve().parents[1]
scratch=(root/'test-results'/'agent-audit-temp').resolve()
assert scratch.is_relative_to(root.resolve())
scratch.mkdir(parents=True,exist_ok=True)
tempfile.tempdir=str(scratch)
sys.stdout.reconfigure(encoding='utf-8')
stream=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(root/'tests'))
result=unittest.TextTestRunner(stream=stream,verbosity=0).run(suite)
report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'ok':result.wasSuccessful(),
        'issues':[{'test':str(t),'detail':d[-1800:]} for t,d in result.failures+result.errors]}
(root/'test-results'/'agent-backend-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(0 if result.wasSuccessful() else 1)
