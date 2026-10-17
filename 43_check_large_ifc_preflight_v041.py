from __future__ import annotations

import json
from pathlib import Path

from fixture_paths import large_ifc_from_env

from ifc_geometry_service import extract_ifc_geometry
from ifc_service import audit_ifc


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
CACHE_DIR = APP_DIR / "runtime" / "regression"


def fixture() -> Path:
    for root in (PROJECT_ROOT, PROJECT_ROOT.parent):
        preferred = large_ifc_from_env()
        if preferred is not None and preferred.exists():
            return preferred
    candidates = []
    for root in (PROJECT_ROOT, PROJECT_ROOT.parent):
        candidates.extend(root.glob("*.ifc"))
    candidates = sorted(candidates, key=lambda p: p.stat().st_size, reverse=True)
    if not candidates:
        raise FileNotFoundError("No IFC fixture found in project root.")
    return candidates[0]


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}: {name}{(' - ' + detail) if detail else ''}")
    if not condition:
        raise AssertionError(name)


def main() -> int:
    path = fixture()
    print("Large IFC Preflight v0.4.1")
    print("=" * 68)
    print(f"File: {path}")

    audit = audit_ifc(path)
    large = audit.get("large_model", {})
    counts = large.get("simulation_counts", {})

    check("IFC schema is IFC2X3", audit.get("schema") == "IFC2X3")
    check("36 building storeys", len(audit.get("spatial", {}).get("storeys", [])) == 36)
    check("Large Model Mode detected", large.get("detected") is True)
    check("Structural-heavy profile detected", large.get("structural_like") is True)
    check("920 walls", counts.get("walls") == 920)
    check("1112 slab panels", counts.get("slabs") == 1112)
    check("434 columns", counts.get("columns") == 434)
    check("1067 beams auto-excluded", counts.get("beams_excluded") == 1067)
    check("3 stairs + 4 flights", (counts.get("stairs", 0) + counts.get("stair_flights", 0)) == 7)
    check("no architectural doors", counts.get("doors") == 0)

    # Choose the busiest storey so the geometry test exercises a meaningful subset.
    storeys = audit["spatial"]["storeys"]
    selected = max(storeys, key=lambda row: int((row.get("counts") or {}).get("total", 0)))
    storey_id = int(selected["entity_id"])
    print(f"Selected storey for lazy-load test: {selected['name']} (#{storey_id})")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    geom = extract_ifc_geometry(
        path,
        cache_path=CACHE_DIR / f"large_storey_{storey_id}.json",
        mode="simulation_relevant",
        storey_ids=[storey_id],
    )

    check("storey-lazy geometry extracted", geom.get("element_count", 0) > 0)
    check("geometry produced triangles", geom.get("triangle_count", 0) > 0)
    check("no IfcBeam in default payload", "IfcBeam" not in (geom.get("categories") or {}))
    check("request records selected storey", geom.get("request", {}).get("storey_ids") == [storey_id])

    print("Geometry subset summary:")
    print(json.dumps({
        "elements": geom.get("element_count"),
        "triangles": geom.get("triangle_count"),
        "mesh_failures": len(geom.get("mesh_failures") or []),
        "categories": geom.get("categories"),
    }, ensure_ascii=False, indent=2))

    print("=" * 68)
    print("LARGE IFC PREFLIGHT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
