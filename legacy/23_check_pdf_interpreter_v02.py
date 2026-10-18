import json
import math
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CANDIDATE_FILE = PROJECT_DIR / "candidate_model_v02.json"
GEOMETRY_FILE = PROJECT_DIR / "geometry_from_pdf_interpreted.json"


def close(a, b, tol=0.08):
    return abs(float(a) - float(b)) <= tol


def main():
    candidates = json.loads(CANDIDATE_FILE.read_text(encoding="utf-8"))
    geometry = json.loads(GEOMETRY_FILE.read_text(encoding="utf-8"))

    failures = []

    def check(cond, message):
        if cond:
            print("PASS:", message)
        else:
            print("FAIL:", message)
            failures.append(message)

    print("PDF Interpreter v0.2 Regression")
    print("=" * 60)

    check(len(candidates["pages"]) == 2, "2 pages interpreted")
    check(all(close(p["scale_denominator"], 100.0, 1e-6) for p in candidates["pages"]), "explicit scale 1:100 detected on both pages")
    check([p["level_key"] for p in candidates["pages"]] == [1, 2], "LEVEL 1 / LEVEL 2 text detected")
    check(all(close(p["floor_size_m"][0], 20.0) and close(p["floor_size_m"][1], 15.0) for p in candidates["pages"]), "floor boundary normalized to 20 x 15 m")

    all_c = [c for p in candidates["pages"] for c in p["candidates"]]
    by_type = {}
    for c in all_c:
        by_type.setdefault(c["type"], []).append(c)

    check(len(by_type.get("wall", [])) == 3, "3 semantic walls detected")
    check(len(by_type.get("column", [])) == 3, "3 columns detected")
    check(len(by_type.get("equipment", [])) == 1, "equipment detected from EQ text + rectangle")
    check(len(by_type.get("stairway", [])) == 1, "stairway detected from treads + UP text")
    check(len(by_type.get("unknown_rectangle", [])) >= 1, "ambiguous rectangle routed to review")

    walls_l1 = [c for c in by_type.get("wall", []) if c["properties"]["level_key"] == 1]
    opening_walls = [c for c in walls_l1 if c["properties"].get("openings")]
    check(len(opening_walls) == 1, "door opening associated with one Level 1 wall")
    if opening_walls:
        op = opening_walls[0]["properties"]["openings"][0]
        check(close(op["width"], 1.80, 0.10), "door width approximately 1.80 m")
        check(op["confidence"] >= 0.90, "door confidence >= 0.90")
        check(any("door_label" in e for e in op["evidence"]), "door evidence includes D01 label")
        check("door_leaf_line" in op["evidence"], "door evidence includes leaf line")

    stair = by_type.get("stairway", [None])[0]
    if stair:
        check(stair["status"] == "review_recommended", "stair routed to review because step count is assumed")
        check(stair["properties"]["start_level"] == 1 and stair["properties"]["end_level"] == 2, "stair connects Level 1 -> Level 2")

    check(len(geometry["levels"]) == 2, "handoff geometry has 2 levels")
    check(len(geometry["areas"]) == 2, "handoff geometry has 2 areas")
    check(len(geometry["walls"]) == 3, "handoff geometry has 3 walls")
    check(len(geometry["columns"]) == 3, "handoff geometry has 3 columns")
    check(len(geometry["obstacles"]) == 1, "handoff geometry has 1 equipment obstacle")
    check(len(geometry["vertical_connections"]) == 1, "provisional stair included in geometry handoff")

    print()
    if failures:
        print(f"REGRESSION RESULT: FAIL ({len(failures)} issue(s))")
        for f in failures:
            print(" -", f)
        sys.exit(1)

    print("REGRESSION RESULT: PASS")


if __name__ == "__main__":
    main()
