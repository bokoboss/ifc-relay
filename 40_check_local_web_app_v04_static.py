from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
index = (APP_DIR / 'static' / 'index.html').read_text(encoding='utf-8')
js = (APP_DIR / 'static' / 'app.js').read_text(encoding='utf-8')
app = (APP_DIR / 'app.py').read_text(encoding='utf-8')
service = (APP_DIR / 'vissim_build_service.py').read_text(encoding='utf-8')
adapter = (APP_DIR / '40_vissim_build_adapter_v04.py').read_text(encoding='utf-8')

checks = {
    'UI has Validate button': 'id="validateBtn"' in index,
    'UI has Build Viswalk button': 'id="buildViswalkBtn"' in index,
    'UI has Download .inpx button': 'id="downloadInpxTopBtn"' in index,
    'UI has Build section': 'id="buildSection"' in index,
    'JS calls /api/validate': "'/api/validate'" in js,
    'JS calls /api/build-vissim': "'/api/build-vissim'" in js,
    'JS downloads latest INPX': '/api/build/latest/download' in js,
    'App exposes build endpoint': '@app.post("/api/build-vissim")' in app,
    'App exposes validation endpoint': '@app.post("/api/validate")' in app,
    'Build service uses subprocess isolation': 'subprocess.run' in service,
    'Adapter repoints JSON_FILE instead of overwriting geometry_v03.json': 'engine.JSON_FILE = input_path' in adapter,
    'Adapter auto-closes Vissim prompt': 'builtins.input = lambda' in adapter,
    'Three loader keeps v0.4 cache tag': "app3d.js?v=040" in js,
}

print('Local Web App v0.4 Static QA')
print('=' * 68)
failed = 0
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ': ' + name)
    failed += 0 if ok else 1
print('=' * 68)
if failed:
    print(f'STATIC QA: FAIL ({failed})')
    raise SystemExit(1)
print('STATIC QA: PASS')
