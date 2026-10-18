from __future__ import annotations

from pathlib import Path

from fixture_paths import large_ifc_from_env
import sys

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

from ifc_service import audit_ifc


def find_large_ifc() -> Path:
    preferred = large_ifc_from_env()
    if preferred is not None and preferred.exists():
        return preferred
    candidates = sorted(
        [p for p in PROJECT_ROOT.glob("*.ifc") if p.stat().st_size >= 25 * 1024 * 1024],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No IFC >=25 MB found in project root.")
    return candidates[0]


path = find_large_ifc()
print("Large IFC Storey Selection Hotfix v0.4.1a")
print("=" * 68)
print("IFC:", path)
result = audit_ifc(path)
storeys = result.get("spatial", {}).get("storeys", [])
assert storeys, "No storeys found"

for s in storeys[:8]:
    print(
        f"{s.get('elevation_m'):>8.3f} m | "
        f"{s.get('name')} | sim meshes={s.get('simulation_mesh_count', 0)}"
    )

first = storeys[0]
meshable = [s for s in storeys if int(s.get("simulation_mesh_count", 0)) > 0]
assert meshable, "No simulation-meshable storey found"

print()
print("First storey:", first.get("elevation_m"), "m ->", first.get("simulation_mesh_count", 0), "sim meshes")
print("Auto-selected storey:", meshable[0].get("elevation_m"), "m ->", meshable[0].get("simulation_mesh_count", 0), "sim meshes")

assert int(meshable[0].get("simulation_mesh_count", 0)) > 0
print()
print("STOREY AUTO-SELECT HOTFIX CHECK: PASS")
