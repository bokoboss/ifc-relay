from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
vendor = ROOT / "static" / "vendor"
three_module = vendor / "three.module.js"
three_core = vendor / "three.core.js"
orbit = vendor / "jsm" / "controls" / "OrbitControls.js"
app3d = ROOT / "static" / "app3d.js"

checks = []

def add(name, ok, detail=""):
    checks.append((name, bool(ok), detail))

add("three.module.js exists", three_module.exists(), str(three_module))
add("OrbitControls.js exists", orbit.exists(), str(orbit))
add("app3d.js exists", app3d.exists(), str(app3d))

module_text = three_module.read_text(encoding="utf-8", errors="replace") if three_module.exists() else ""
core_needed = "./three.core.js" in module_text
add("three.module.js dependency inspected", bool(module_text))

if core_needed:
    add("three.core.js exists", three_core.exists(), str(three_core))
    if three_core.exists():
        add("three.core.js size looks valid", three_core.stat().st_size > 100_000, f"{three_core.stat().st_size} bytes")
else:
    add("three.core.js not required by this module build", True)

orbit_text = orbit.read_text(encoding="utf-8", errors="replace") if orbit.exists() else ""
add("OrbitControls has no bare three import", "from 'three'" not in orbit_text and 'from "three"' not in orbit_text)
add("OrbitControls points to local three.module.js", "../../three.module.js" in orbit_text)

app3d_text = app3d.read_text(encoding="utf-8", errors="replace") if app3d.exists() else ""
add("app3d imports local three.module.js", "./vendor/three.module.js" in app3d_text)
add("app3d imports local OrbitControls", "./vendor/jsm/controls/OrbitControls.js" in app3d_text)

print("Three.js Dependency Diagnostic v0.2.3")
print("=" * 64)
print(f"three.module.js references three.core.js: {core_needed}")
print()

failures = 0
for name, ok, detail in checks:
    if ok:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name}")
        if detail:
            print(f"      {detail}")
        failures += 1

print()
if failures:
    print(f"THREE DEPENDENCY CHECK: FAIL ({failures} issue(s))")
    sys.exit(1)

print("THREE DEPENDENCY CHECK: PASS")
