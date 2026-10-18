import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
GEOMETRY_FILE = PROJECT_DIR / "geometry_from_pdf_workspace_v03.json"
REPORT_FILE = PROJECT_DIR / "output" / "review_workspace_v03_handoff_report.json"
TOL = 0.03


def close(a, b, tol=TOL):
    return abs(float(a) - float(b)) <= tol


def main():
    geometry = json.loads(GEOMETRY_FILE.read_text(encoding="utf-8"))
    report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))

    failures = []

    def check(condition, message):
        if condition:
            print("PASS:", message)
        else:
            print("FAIL:", message)
            failures.append(message)

    print("Wall Opening Regression v0.3")
    print("=" * 60)

    walls = geometry["walls"]
    logical = report.get("wall_segmentation", [])
    with_opening = [item for item in logical if item.get("opening_count", 0) > 0]

    check(len(logical) >= 1, "logical wall segmentation report exists")
    check(len(with_opening) == 1, "exactly one logical wall contains an opening in the sample")
    check(all(not wall.get("openings") for wall in walls), "physical Vissim wall segments contain no hidden opening metadata")
    check(report.get("physical_wall_segment_count") == len(walls), "reported physical wall count matches geometry output")

    if with_opening:
        info = with_opening[0]
        logical_id = info["logical_wall_id"]
        opening = info["openings"][0]
        logical_start = info["logical_start"]
        logical_end = info["logical_end"]

        physical = [
            wall for wall in walls
            if wall.get("source_logical_wall_id") == logical_id
        ]

        check(len(physical) == 2, f"{logical_id} is physically split into two wall segments")

        if len(physical) == 2:
            sx, sy = logical_start
            ex, ey = logical_end
            dx = ex - sx
            dy = ey - sy
            length = (dx * dx + dy * dy) ** 0.5
            ux = dx / length
            uy = dy / length

            def project(point):
                return (point[0] - sx) * ux + (point[1] - sy) * uy

            spans = []
            for wall in physical:
                a = project(wall["start"])
                b = project(wall["end"])
                spans.append((min(a, b), max(a, b)))
            spans.sort()
            left, right = spans

            gap_start = left[1]
            gap_end = right[0]
            gap_width = gap_end - gap_start
            expected_width = float(opening["width"])
            expected_center = float(opening["distance_along_wall"])

            check(close(left[0], 0.0), "first physical segment begins at logical wall start")
            check(close(right[1], length), "last physical segment ends at logical wall end")
            check(close(gap_width, expected_width), f"physical door gap width matches reviewed opening width ({expected_width:.2f} m)")
            check(close((gap_start + gap_end) / 2.0, expected_center), "physical door gap is centered on reviewed door position")

            print()
            print("Door opening geometry:")
            print(f"  logical wall       : {logical_id}")
            print(f"  opening center     : {expected_center:.3f} m along wall")
            print(f"  opening width      : {expected_width:.3f} m")
            print(f"  physical gap       : {gap_start:.3f} -> {gap_end:.3f} m")

    print()
    print("=" * 60)
    if failures:
        print(f"REGRESSION RESULT: FAIL ({len(failures)} issue(s))")
        raise SystemExit(1)
    print("REGRESSION RESULT: PASS")


if __name__ == "__main__":
    main()
