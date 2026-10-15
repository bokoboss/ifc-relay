from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from ifc_geometry_service import extract_ifc_geometry
from ifc_semantic_service import build_semantic_model, write_semantic_model


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
IFC_PATH = PROJECT_ROOT / "TallBuilding.ifc"
CACHE_PATH = APP_DIR / "runtime" / "cache" / "TallBuilding_geometry_v02.json"
OUTPUT_PATH = APP_DIR / "runtime" / "semantic" / "TallBuilding_geometry_v03_regression.json"
ENGINE_PATH = PROJECT_ROOT / "05_geometry_engine_v03.py"


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {label}")
        return
    if detail:
        print(f"FAIL: {label} -- {detail}")
    else:
        print(f"FAIL: {label}")
    raise AssertionError(label)


def load_engine_module():
    spec = importlib.util.spec_from_file_location("geometry_engine_v03", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load engine: {ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    print("IFC -> Semantic Model v0.3 Regression")
    print("=" * 64)

    check("TallBuilding.ifc exists", IFC_PATH.exists(), str(IFC_PATH))
    check("Geometry Engine v0.3 exists", ENGINE_PATH.exists(), str(ENGINE_PATH))

    geometry = extract_ifc_geometry(IFC_PATH, cache_path=CACHE_PATH)
    check("3D mesh extraction = 55", geometry.get("element_count") == 55, str(geometry.get("element_count")))
    check("3D mesh failures = 0", len(geometry.get("mesh_failures", [])) == 0)

    semantic = build_semantic_model(IFC_PATH, geometry, {})
    write_semantic_model(OUTPUT_PATH, semantic)
    summary = semantic["ifc_semantic"]["summary"]

    check("Levels = 5", summary["levels"] == 5, str(summary["levels"]))
    check("Walkable floor areas = 4", summary["walkable_areas"] == 4, str(summary["walkable_areas"]))
    check("Logical walls = 24", summary["logical_walls"] == 24, str(summary["logical_walls"]))
    check("Physical wall segments = 29", summary["physical_wall_segments"] == 29, str(summary["physical_wall_segments"]))
    check("Included doors = 5", summary["included_doors"] == 5, str(summary["included_doors"]))
    check("Door openings applied = 5", summary["door_openings_applied"] == 5, str(summary["door_openings_applied"]))
    check("Windows never create pedestrian openings", summary["windows_used_as_openings"] == 0)
    check("Source windows = 21", summary["source_windows"] == 21, str(summary["source_windows"]))
    check("No vertical connections in source fixture", summary["vertical_connections"] == 0)

    walls = semantic.get("walls", [])
    check("Engine-facing walls contain no hidden openings", all("openings" not in wall for wall in walls))
    check("All engine-facing walls are marked physical segments", all(wall.get("physical_segment") is True for wall in walls))

    # Ensure the roof slab is not silently promoted to a pedestrian area.
    check("Only FLOOR slabs become walkable areas", len(semantic.get("areas", [])) == 4)

    engine = load_engine_module()
    levels, areas, obstacles, vertical = engine.build_geometry_model(semantic)
    check("Geometry Engine accepts generated semantic JSON", True)
    check("Engine semantic obstacle count = 29", len(obstacles) == 29, str(len(obstacles)))

    engine_warnings = engine.validate_model(levels, areas, obstacles, vertical)
    vissim_obstacles = engine.prepare_vissim_obstacles(obstacles)
    check("No second wall fragmentation is required", len(vissim_obstacles) == len(obstacles), f"{len(vissim_obstacles)} vs {len(obstacles)}")

    print()
    print("Semantic summary:")
    print(json.dumps(summary, indent=2))
    print(f"Engine validation warnings: {len(engine_warnings)}")
    for warning in engine_warnings[:10]:
        print("  -", warning)
    if len(engine_warnings) > 10:
        print(f"  ... {len(engine_warnings) - 10} more")

    print()
    print("Output:", OUTPUT_PATH)
    print("=" * 64)
    print("REGRESSION RESULT: PASS")


if __name__ == "__main__":
    main()
