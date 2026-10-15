from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

checks = []

def add(name, ok):
    checks.append((name, bool(ok)))

app = (ROOT / "app.py").read_text(encoding="utf-8")
ifc = (ROOT / "ifc_service.py").read_text(encoding="utf-8")
geom = (ROOT / "ifc_geometry_service.py").read_text(encoding="utf-8")
semantic = (ROOT / "ifc_semantic_service.py").read_text(encoding="utf-8")
html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
app3d = (ROOT / "static" / "app3d.js").read_text(encoding="utf-8")

add("app version 0.4.1", 'version="0.4.1"' in app)
add("large-model audit metadata", '"large_model"' in ifc)
add("BASESLAB is review-only", '"BASESLAB"' in ifc and 'Foundation/base slab' in ifc)
add("filtered geometry modes", 'mode: str = "simulation_relevant"' in geom)
add("storey-lazy geometry filter", 'storey_ids' in geom and 'requested_storeys' in geom)
add("triangle count emitted", '"triangle_count"' in geom)
add("walkable slab consolidation", 'merge_walkable_components' in semantic)
add("walkable void masks", 'walkable_void_mask' in semantic)
add("large-model UI panel", 'id="largeModelSection"' in html)
add("3D load mode selector", 'id="geometryLoadMode"' in html)
add("storey selector", 'id="geometryStoreySelect"' in html)
add("browser sends geometry request JSON", 'geometryRequestFromControls' in js)
add("semantic uses source slab metric", 'semanticSourceSlabs' in js)
add("3D viewer supports append", 'const append = !!options.append' in app3d)
add("Three loader cache-bust v041", "app3d.js?v=041" in js)

print("Local Web App v0.4.1 Static QA")
print("=" * 68)
fail = 0
for name, ok in checks:
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
    fail += 0 if ok else 1
print("=" * 68)
if fail:
    print(f"STATIC QA: FAIL ({fail})")
    raise SystemExit(1)
print("STATIC QA: PASS")
