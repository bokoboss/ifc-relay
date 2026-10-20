from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
ADAPTER = APP_DIR / '40_vissim_build_adapter_v04.py'
INPUT = PROJECT_ROOT / 'geometry_ifc_v03.json'
if not INPUT.exists():
    candidates = sorted((PROJECT_ROOT / 'local_web_app_v03' / 'runtime' / 'semantic').glob('*_geometry_v03.json')) if (PROJECT_ROOT / 'local_web_app_v03' / 'runtime' / 'semantic').exists() else []
    if candidates:
        INPUT = candidates[-1]
OUTPUT = APP_DIR / 'runtime' / 'validation' / 'regression_validation_v04.json'
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

print('Build Adapter v0.4 Validation Regression')
print('=' * 68)

def check(name, ok, detail=''):
    print(('PASS' if ok else 'FAIL') + ': ' + name)
    if detail and not ok:
        print('      ' + detail)
    if not ok:
        raise SystemExit(1)

check('Build adapter exists', ADAPTER.exists(), str(ADAPTER))
check('Engine input geometry_ifc_v03.json exists', INPUT.exists(), str(INPUT))
check('Geometry Engine v0.3 exists', (PROJECT_ROOT / '05_geometry_engine_v03.py').exists())
check('base_empty.inpx exists', (PROJECT_ROOT / 'base_empty.inpx').exists())

proc = subprocess.run([
    sys.executable, str(ADAPTER),
    '--project-root', str(PROJECT_ROOT),
    '--input', str(INPUT),
    '--validation-output', str(OUTPUT),
    '--validate-only',
], cwd=APP_DIR, capture_output=True, text=True, check=False)

if proc.stdout:
    print(proc.stdout)
if proc.stderr:
    print(proc.stderr)
check('Adapter validate-only exit code = 0', proc.returncode == 0)
check('Validation JSON created', OUTPUT.exists(), str(OUTPUT))

result = json.loads(OUTPUT.read_text(encoding='utf-8'))
summary = result.get('summary', {})
counts = result.get('severity_counts', {})
check('Levels = 5', summary.get('levels') == 5, str(summary))
check('Areas = 4', summary.get('areas') == 4, str(summary))
check('Semantic obstacles = 29', summary.get('semantic_obstacles') == 29, str(summary))
check('Vissim obstacles = 29', summary.get('vissim_obstacles') == 29, str(summary))
check('Blocking errors = 0', counts.get('error') == 0, str(counts))
check('Warnings = 0 for TallBuilding expected-boundary cases', counts.get('warning') == 0, str(counts))
check('Information = 9', counts.get('info') == 9, str(counts))
check('Build allowed', result.get('build_allowed') is True)

print('=' * 68)
print('BUILD ADAPTER v0.4 VALIDATION: PASS')
