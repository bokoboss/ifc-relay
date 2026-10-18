import json
import math
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
GEOMETRY_FILE = PROJECT_DIR / "geometry_from_pdf_vector.json"
REPORT_FILE = PROJECT_DIR / "output" / "pdf_vector_ingestion_report.json"

TOL = 0.04


def close(a, b, tol=TOL):
    return abs(float(a) - float(b)) <= tol


def ok(message):
    print("PASS:", message)


def fail(message, failures):
    print("FAIL:", message)
    failures.append(message)


def main():
    if not GEOMETRY_FILE.exists():
        raise FileNotFoundError(GEOMETRY_FILE)
    if not REPORT_FILE.exists():
        raise FileNotFoundError(REPORT_FILE)

    model = json.loads(GEOMETRY_FILE.read_text(encoding="utf-8"))
    report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))

    failures = []

    print("PDF Vector Regression Check")
    print("=" * 60)

    if report["pages"] == 2:
        ok("2 PDF pages ingested")
    else:
        fail(f"Expected 2 pages, got {report['pages']}", failures)

    if len(model["levels"]) == 2:
        ok("2 levels detected")
    else:
        fail(f"Expected 2 levels, got {len(model['levels'])}", failures)

    level_map = {x["key"]: x for x in model["levels"]}
    if (
        1 in level_map
        and 2 in level_map
        and close(level_map[1]["z"], 0.0)
        and close(level_map[2]["z"], 4.0)
    ):
        ok("Level elevations = 0 m / 4 m")
    else:
        fail(f"Unexpected levels: {model['levels']}", failures)

    if len(model["areas"]) == 2:
        ok("2 walkable areas detected")
    else:
        fail(f"Expected 2 areas, got {len(model['areas'])}", failures)

    if model["areas"]:
        pts = model["areas"][0]["polygon"]
        width = max(p[0] for p in pts) - min(p[0] for p in pts)
        height = max(p[1] for p in pts) - min(p[1] for p in pts)
        if close(width, 20.0) and close(height, 15.0):
            ok("Drawing scale recovered: L1 area = 20 x 15 m")
        else:
            fail(f"Unexpected L1 area size: {width} x {height}", failures)

    if len(model["walls"]) == 3:
        ok("3 wall centerlines detected across 2 levels")
    else:
        fail(f"Expected 3 walls, got {len(model['walls'])}", failures)

    door_walls = [w for w in model["walls"] if w.get("openings")]
    if len(door_walls) == 1:
        opening = door_walls[0]["openings"][0]
        if close(opening["width"], 1.8):
            ok("Door associated to wall with width ~1.80 m")
        else:
            fail(f"Door width unexpected: {opening['width']}", failures)
    else:
        fail(f"Expected exactly 1 wall with door, got {len(door_walls)}", failures)

    if len(model["columns"]) == 3:
        ok("3 columns detected")
    else:
        fail(f"Expected 3 columns, got {len(model['columns'])}", failures)

    l1_rect = None
    for col in model["columns"]:
        if col["level_key"] == 1 and col["shape"] == "rectangle":
            if close(max(col["width"], col["depth"]), 0.60) and close(
                min(col["width"], col["depth"]), 0.40
            ):
                l1_rect = col
                break

    if l1_rect:
        ok("Rotated 0.60 x 0.40 m column recovered")
    else:
        fail("Rotated L1 rectangular column not recovered", failures)

    circle_cols = [c for c in model["columns"] if c["shape"] == "circle"]
    if circle_cols and close(circle_cols[0]["diameter"], 0.80):
        ok("Circular column diameter ~0.80 m recovered")
    else:
        fail("0.80 m circular column not recovered", failures)

    if len(model["obstacles"]) == 1:
        ok("1 equipment obstacle detected")
    else:
        fail(f"Expected 1 equipment obstacle, got {len(model['obstacles'])}", failures)

    if len(model["vertical_connections"]) == 1:
        vc = model["vertical_connections"][0]
        if vc["start_level"] == 1 and vc["end_level"] == 2:
            ok("Stair L1 -> L2 detected")
        else:
            fail(
                f"Unexpected stair levels: {vc['start_level']} -> {vc['end_level']}",
                failures,
            )
    else:
        fail(
            f"Expected 1 vertical connection, got {len(model['vertical_connections'])}",
            failures,
        )

    if report["doors_assigned"] == 1 and not report["doors_unassigned"]:
        ok("Door association report PASS")
    else:
        fail("Door association report not clean", failures)

    print()
    print("=" * 60)

    if failures:
        print(f"REGRESSION RESULT: FAIL ({len(failures)} issue(s))")
        for item in failures:
            print(" -", item)
        sys.exit(1)

    print("REGRESSION RESULT: PASS")


if __name__ == "__main__":
    main()
