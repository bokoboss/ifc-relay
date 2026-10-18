from __future__ import annotations

import json
import time
from pathlib import Path

from fixture_paths import large_ifc_from_env

from ifc_geometry_service import extract_ifc_geometry
from ifc_semantic_service import build_semantic_model, write_semantic_model
from vissim_build_service import validate_engine_input


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
RUNTIME = APP_DIR / "runtime" / "large_semantic_regression"


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
        raise FileNotFoundError("Large IFC fixture not found.")
    return candidates[0]


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}: {name}{(' - ' + detail) if detail else ''}")
    if not condition:
        raise AssertionError(name)


def main() -> int:
    path = fixture()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cache = RUNTIME / "simulation_relevant_all.json"
    output = RUNTIME / "large_geometry_v041.json"

    print("Large IFC Full Semantic Regression v0.4.1")
    print("=" * 72)
    print(f"File: {path}")
    print("NOTE: this is the heavy regression; first run may take several minutes.")

    t0 = time.perf_counter()
    geometry = extract_ifc_geometry(
        path,
        cache_path=cache,
        mode="simulation_relevant",
        storey_ids=[],
    )
    t1 = time.perf_counter()

    semantic = build_semantic_model(path, geometry, {})
    write_semantic_model(output, semantic)
    t2 = time.perf_counter()

    summary = semantic["ifc_semantic"]["summary"]

    check("36 levels", summary.get("levels") == 36)
    check("981 FLOOR/LANDING source slabs auto-included", summary.get("walkable_source_slabs") == 981)
    check(
        "floor panels consolidated",
        0 < summary.get("walkable_regions", 0) < summary.get("walkable_source_slabs", 0),
        f"{summary.get('walkable_source_slabs')} slabs -> {summary.get('walkable_regions')} regions",
    )
    check("no architectural door openings", summary.get("door_openings_applied") == 0)
    check("complex stairs remain review-only by default", summary.get("vertical_connections") == 0)
    check("IfcBeam excluded from semantic geometry cache", "IfcBeam" not in (geometry.get("categories") or {}))
    check("geometry mesh failures are zero", len(geometry.get("mesh_failures") or []) == 0)

    validation = validate_engine_input(APP_DIR, PROJECT_ROOT, output)
    check("Geometry Engine validation build allowed", validation.get("build_allowed") is True)

    print("\nSummary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nPerformance:")
    print(json.dumps({
        "geometry_extract_sec": round(t1 - t0, 2),
        "semantic_build_sec": round(t2 - t1, 2),
        "mesh_elements": geometry.get("element_count"),
        "triangles": geometry.get("triangle_count"),
        "validation_severity": validation.get("severity_counts"),
        "output": str(output),
    }, ensure_ascii=False, indent=2))

    print("=" * 72)
    print("LARGE IFC FULL SEMANTIC REGRESSION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
