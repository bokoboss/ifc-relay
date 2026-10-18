import json
import math
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent

GEOMETRY_FILE = (
    PROJECT_DIR
    / "geometry_from_dxf_v02.json"
)

REPORT_FILE = (
    PROJECT_DIR
    / "output"
    / "dxf_ingestion_v02_report.json"
)

TOL = 0.03


def close(a, b, tol=TOL):
    return abs(float(a) - float(b)) <= tol


def fail(message, failures):
    print("FAIL:", message)
    failures.append(message)


def ok(message):
    print("PASS:", message)


def main():

    if not GEOMETRY_FILE.exists():
        raise FileNotFoundError(
            f"Geometry file not found: {GEOMETRY_FILE}"
        )

    if not REPORT_FILE.exists():
        raise FileNotFoundError(
            f"Report file not found: {REPORT_FILE}"
        )

    with GEOMETRY_FILE.open(
        "r",
        encoding="utf-8",
    ) as f:
        model = json.load(f)

    with REPORT_FILE.open(
        "r",
        encoding="utf-8",
    ) as f:
        report = json.load(f)

    failures = []

    print("DXF Regression Check")
    print("=" * 60)

    # ========================================================
    # UNITS
    # ========================================================

    scale = float(
        report["scale_to_meters"]
    )

    if close(
        scale,
        0.001,
        tol=1e-9,
    ):
        ok("mm -> m scale = 0.001")
    else:
        fail(
            f"Expected scale 0.001, got {scale}",
            failures,
        )

    # ========================================================
    # LEVELS
    # ========================================================

    levels = model["levels"]

    if len(levels) == 2:
        ok("2 levels detected")
    else:
        fail(
            f"Expected 2 levels, got {len(levels)}",
            failures,
        )

    level_map = {
        item["key"]: item
        for item in levels
    }

    if (
        1 in level_map
        and 2 in level_map
        and close(level_map[1]["z"], 0.0)
        and close(level_map[2]["z"], 4.0)
    ):
        ok("Level elevations = 0 m / 4 m")
    else:
        fail(
            f"Unexpected level definitions: {levels}",
            failures,
        )

    # ========================================================
    # AREAS
    # ========================================================

    areas = model["areas"]

    if len(areas) == 2:
        ok("2 walkable areas detected")
    else:
        fail(
            f"Expected 2 areas, got {len(areas)}",
            failures,
        )

    # Check first area extents are 20 x 15 m.
    if areas:
        xs = [
            p[0]
            for p in areas[0]["polygon"]
        ]
        ys = [
            p[1]
            for p in areas[0]["polygon"]
        ]

        width = max(xs) - min(xs)
        depth = max(ys) - min(ys)

        if (
            close(width, 20.0)
            and close(depth, 15.0)
        ):
            ok("L1 area scaled to 20 x 15 m")
        else:
            fail(
                f"Unexpected L1 area size: {width} x {depth}",
                failures,
            )

    # ========================================================
    # WALLS
    # ========================================================

    walls = model["walls"]

    if len(walls) >= 4:
        ok(
            f"Wall parser produced {len(walls)} wall segments"
        )
    else:
        fail(
            f"Expected >= 4 wall segments, got {len(walls)}",
            failures,
        )

    # Find horizontal wall near y=3m, length ~16m,
    # thickness ~0.2m. This should be the paired double wall.
    paired_wall = None

    for wall in walls:
        sx, sy = wall["start"]
        ex, ey = wall["end"]

        length = math.hypot(
            ex - sx,
            ey - sy,
        )

        if (
            wall["level_key"] == 1
            and abs(sy - 3.0) < 0.05
            and abs(ey - 3.0) < 0.05
            and abs(length - 16.0) < 0.05
        ):
            paired_wall = wall
            break

    if paired_wall is None:
        fail(
            "Double-line wall centerline at y=3m not found",
            failures,
        )
    else:
        if close(
            paired_wall["thickness"],
            0.20,
            tol=0.02,
        ):
            ok(
                "Double-line wall paired with ~0.20 m thickness"
            )
        else:
            fail(
                "Double-line wall thickness "
                f"expected 0.20m, got {paired_wall['thickness']}",
                failures,
            )

        openings = paired_wall.get(
            "openings",
            [],
        )

        if len(openings) == 1:
            opening = openings[0]

            if close(
                opening["width"],
                1.80,
                tol=0.03,
            ):
                ok(
                    "Door block assigned to paired wall, width ~1.80 m"
                )
            else:
                fail(
                    f"Door width expected 1.80m, got {opening['width']}",
                    failures,
                )
        else:
            fail(
                f"Expected 1 door on paired wall, got {len(openings)}",
                failures,
            )

    # ========================================================
    # COLUMNS
    # ========================================================

    columns = model["columns"]

    if len(columns) == 3:
        ok("3 columns detected across 2 levels")
    else:
        fail(
            f"Expected 3 columns, got {len(columns)}",
            failures,
        )

    rotated_rect = None

    for col in columns:
        if (
            col["level_key"] == 1
            and col["shape"] == "rectangle"
            and close(
                max(
                    col["width"],
                    col["depth"],
                ),
                0.60,
                tol=0.03,
            )
            and close(
                min(
                    col["width"],
                    col["depth"],
                ),
                0.40,
                tol=0.03,
            )
        ):
            rotated_rect = col
            break

    if rotated_rect:
        # Minimum rotated rectangle can return the axis direction
        # equivalent modulo 90 degrees.
        angle = (
            float(
                rotated_rect[
                    "rotation_deg"
                ]
            )
            % 90.0
        )

        if (
            abs(angle - 30.0) < 1.0
            or abs(angle - 60.0) < 1.0
        ):
            ok(
                "Rotated column geometry recovered"
            )
        else:
            fail(
                f"Unexpected rotated column angle: {angle}",
                failures,
            )
    else:
        fail(
            "Rotated 0.60 x 0.40 m L1 column not found",
            failures,
        )

    # ========================================================
    # EQUIPMENT
    # ========================================================

    obstacles = model["obstacles"]

    if len(obstacles) == 1:
        ok("1 fixed equipment obstacle detected")
    else:
        fail(
            f"Expected 1 obstacle, got {len(obstacles)}",
            failures,
        )

    # ========================================================
    # STAIR / VERTICAL CONNECTION
    # ========================================================

    vcs = model[
        "vertical_connections"
    ]

    if len(vcs) == 1:
        vc = vcs[0]

        if (
            vc["start_level"] == 1
            and vc["end_level"] == 2
        ):
            ok(
                "Stair vertical connection L1 -> L2 detected"
            )
        else:
            fail(
                "Unexpected stair level references: "
                f"{vc['start_level']} -> {vc['end_level']}",
                failures,
            )
    else:
        fail(
            f"Expected 1 vertical connection, got {len(vcs)}",
            failures,
        )

    # ========================================================
    # INGESTION REPORT
    # ========================================================

    if (
        report.get(
            "double_line_wall_pairs",
            0,
        )
        >= 1
    ):
        ok(
            "Report confirms double-line wall pairing"
        )
    else:
        fail(
            "No double-line wall pairing reported",
            failures,
        )

    if (
        report.get(
            "doors_assigned",
            0,
        )
        >= 1
    ):
        ok(
            "Report confirms assigned door"
        )
    else:
        fail(
            "No assigned door reported",
            failures,
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("=" * 60)

    if failures:
        print(
            f"REGRESSION RESULT: FAIL "
            f"({len(failures)} issue(s))"
        )

        for item in failures:
            print(" -", item)

        sys.exit(1)

    print("REGRESSION RESULT: PASS")


if __name__ == "__main__":
    main()
