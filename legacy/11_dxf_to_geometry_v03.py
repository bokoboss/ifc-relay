import json
import math
import re
from pathlib import Path

import ezdxf
from shapely.geometry import LineString, Point


# ============================================================
# CONFIG
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent

DXF_FILE = PROJECT_DIR / "sample_floorplan.dxf"
OUTPUT_JSON = PROJECT_DIR / "geometry_from_dxf.json"

LAYER_PREFIX = "VW_"

DEFAULTS = {
    "wall_thickness": 0.20,
    "wall_height": 3.00,
    "column_height": 3.00,
    "obstacle_height": 1.20,
    "z_offset": 0.0,
}

LEVEL_Z = {
    1: 0.0,
}

DOOR_TO_WALL_TOLERANCE = 0.10
PARALLEL_ANGLE_TOLERANCE_DEG = 5.0


# ============================================================
# HELPERS
# ============================================================

def entity_layer(entity):
    return str(entity.dxf.layer).upper().strip()


def parse_layer(layer_name):
    """
    Expected:
      VW_AREA_L1
      VW_WALL_L1
      VW_DOOR_L1
      VW_COLUMN_L1
      VW_EQUIPMENT_L1
    """
    pattern = r"^VW_(AREA|WALL|DOOR|COLUMN|EQUIPMENT)_L(\d+)$"
    match = re.match(pattern, layer_name.upper())

    if not match:
        return None

    semantic_type = match.group(1).lower()
    level_key = int(match.group(2))

    return semantic_type, level_key


def line_endpoints(entity):
    start = entity.dxf.start
    end = entity.dxf.end

    return (
        (float(start.x), float(start.y)),
        (float(end.x), float(end.y)),
    )


def lwpolyline_points(entity):
    points = []

    for x, y, *_ in entity.get_points("xy"):
        points.append(
            [float(x), float(y)]
        )

    return points


def normalize_angle(angle):
    angle = angle % 180.0
    if angle < 0:
        angle += 180.0
    return angle


def segment_angle(start, end):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    return normalize_angle(
        math.degrees(math.atan2(dy, dx))
    )


def angle_difference(a, b):
    diff = abs(a - b) % 180.0
    return min(diff, 180.0 - diff)


def midpoint(start, end):
    return [
        (start[0] + end[0]) / 2.0,
        (start[1] + end[1]) / 2.0,
    ]


def distance(start, end):
    return math.hypot(
        end[0] - start[0],
        end[1] - start[1],
    )


def bbox_from_points(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    return (
        min_x,
        min_y,
        max_x,
        max_y,
    )


# ============================================================
# DXF READ
# ============================================================

def read_dxf(path):
    if not path.exists():
        raise FileNotFoundError(
            f"DXF file not found: {path}"
        )

    try:
        return ezdxf.readfile(path)

    except ezdxf.DXFStructureError as exc:
        raise RuntimeError(
            f"Invalid/corrupt DXF: {exc}"
        ) from exc


# ============================================================
# INGESTION
# ============================================================

def ingest(doc):
    msp = doc.modelspace()

    areas = []
    walls = []
    doors = []
    columns = []
    obstacles = []

    ignored = []

    # Deterministic key ranges
    next_area_key = 1001
    next_wall_key = 1101
    next_column_key = 1301
    next_obstacle_key = 1401

    for entity in msp:
        layer = entity_layer(entity)
        mapping = parse_layer(layer)

        if mapping is None:
            ignored.append({
                "type": entity.dxftype(),
                "layer": layer,
            })
            continue

        semantic_type, level_key = mapping
        entity_type = entity.dxftype()

        # ----------------------------------------------------
        # AREA
        # ----------------------------------------------------
        if semantic_type == "area":

            if entity_type != "LWPOLYLINE":
                raise ValueError(
                    f"{layer}: AREA must be LWPOLYLINE, got {entity_type}"
                )

            if not entity.closed:
                raise ValueError(
                    f"{layer}: AREA polyline must be closed."
                )

            points = lwpolyline_points(entity)

            areas.append({
                "key": next_area_key,
                "name": f"DXF Area {next_area_key}",
                "level_key": level_key,
                "polygon": points,
            })

            next_area_key += 1

        # ----------------------------------------------------
        # WALL
        # ----------------------------------------------------
        elif semantic_type == "wall":

            if entity_type != "LINE":
                raise ValueError(
                    f"{layer}: WALL must be LINE, got {entity_type}"
                )

            start, end = line_endpoints(entity)

            walls.append({
                "key": next_wall_key,
                "name": f"DXF Wall {next_wall_key}",
                "level_key": level_key,
                "start": [start[0], start[1]],
                "end": [end[0], end[1]],
                "thickness": DEFAULTS["wall_thickness"],
                "height": DEFAULTS["wall_height"],
                "openings": [],
            })

            next_wall_key += 1

        # ----------------------------------------------------
        # DOOR
        # ----------------------------------------------------
        elif semantic_type == "door":

            if entity_type != "LINE":
                raise ValueError(
                    f"{layer}: DOOR must be LINE, got {entity_type}"
                )

            start, end = line_endpoints(entity)

            doors.append({
                "level_key": level_key,
                "start": start,
                "end": end,
                "center": midpoint(start, end),
                "width": distance(start, end),
                "angle": segment_angle(start, end),
            })

        # ----------------------------------------------------
        # COLUMN
        # ----------------------------------------------------
        elif semantic_type == "column":

            if entity_type == "CIRCLE":

                center = entity.dxf.center
                radius = float(entity.dxf.radius)

                columns.append({
                    "key": next_column_key,
                    "name": f"DXF Column {next_column_key}",
                    "level_key": level_key,
                    "shape": "circle",
                    "center": [
                        float(center.x),
                        float(center.y),
                    ],
                    "diameter": 2.0 * radius,
                    "height": DEFAULTS["column_height"],
                })

                next_column_key += 1

            elif entity_type == "LWPOLYLINE":

                if not entity.closed:
                    raise ValueError(
                        f"{layer}: rectangular COLUMN must be closed."
                    )

                points = lwpolyline_points(entity)
                min_x, min_y, max_x, max_y = bbox_from_points(points)

                columns.append({
                    "key": next_column_key,
                    "name": f"DXF Column {next_column_key}",
                    "level_key": level_key,
                    "shape": "rectangle",
                    "center": [
                        (min_x + max_x) / 2.0,
                        (min_y + max_y) / 2.0,
                    ],
                    "width": max_x - min_x,
                    "depth": max_y - min_y,
                    "rotation_deg": 0.0,
                    "height": DEFAULTS["column_height"],
                })

                next_column_key += 1

            else:
                raise ValueError(
                    f"{layer}: unsupported COLUMN entity {entity_type}"
                )

        # ----------------------------------------------------
        # EQUIPMENT -> RAW OBSTACLE
        # ----------------------------------------------------
        elif semantic_type == "equipment":

            if entity_type != "LWPOLYLINE":
                raise ValueError(
                    f"{layer}: EQUIPMENT must be LWPOLYLINE, got {entity_type}"
                )

            if not entity.closed:
                raise ValueError(
                    f"{layer}: EQUIPMENT polyline must be closed."
                )

            points = lwpolyline_points(entity)

            obstacles.append({
                "key": next_obstacle_key,
                "name": f"DXF Equipment {next_obstacle_key}",
                "type": "equipment",
                "level_key": level_key,
                "height": DEFAULTS["obstacle_height"],
                "z_offset": DEFAULTS["z_offset"],
                "polygon": points,
            })

            next_obstacle_key += 1

    # ========================================================
    # ASSOCIATE DOORS TO WALLS
    # ========================================================

    unassigned_doors = []

    for door_index, door in enumerate(
        doors,
        start=1,
    ):
        door_point = Point(
            door["center"]
        )

        candidates = []

        for wall in walls:

            if wall["level_key"] != door["level_key"]:
                continue

            wall_start = tuple(
                wall["start"]
            )
            wall_end = tuple(
                wall["end"]
            )

            wall_line = LineString(
                [wall_start, wall_end]
            )

            wall_angle = segment_angle(
                wall_start,
                wall_end,
            )

            angle_diff = angle_difference(
                wall_angle,
                door["angle"],
            )

            wall_distance = wall_line.distance(
                door_point
            )

            if (
                wall_distance <= DOOR_TO_WALL_TOLERANCE
                and angle_diff
                <= PARALLEL_ANGLE_TOLERANCE_DEG
            ):
                candidates.append(
                    (
                        wall_distance,
                        angle_diff,
                        wall,
                    )
                )

        if not candidates:
            unassigned_doors.append({
                "door_index": door_index,
                "level_key": door["level_key"],
                "center": door["center"],
                "width": door["width"],
            })
            continue

        candidates.sort(
            key=lambda x: (
                x[0],
                x[1],
                x[2]["key"],
            )
        )

        selected_wall = candidates[0][2]

        selected_wall[
            "openings"
        ].append({
            "name": f"DXF Door D{door_index:02d}",
            "center": door["center"],
            "width": door["width"],
        })

    # ========================================================
    # LEVEL RECORDS
    # ========================================================

    used_levels = set()

    for collection in (
        areas,
        walls,
        columns,
        obstacles,
    ):
        for item in collection:
            used_levels.add(
                int(item["level_key"])
            )

    for door in doors:
        used_levels.add(
            int(door["level_key"])
        )

    levels = []

    for key in sorted(used_levels):
        levels.append({
            "key": key,
            "name": (
                "Ground Floor"
                if key == 1
                else f"Level {key}"
            ),
            "z": float(
                LEVEL_Z.get(
                    key,
                    (key - 1) * 4.0,
                )
            ),
        })

    # ========================================================
    # OUTPUT MODEL
    # ========================================================

    model = {
        "project": {
            "name": "DXF Imported Viswalk Model",
            "units": "m",
            "source": str(DXF_FILE),
        },

        "defaults": {
            "wall_height": DEFAULTS["wall_height"],
            "column_height": DEFAULTS["column_height"],
            "obstacle_height": DEFAULTS["obstacle_height"],
            "z_offset": DEFAULTS["z_offset"],
            "level_key": 1,
        },

        "transform": {
            "scale": 1.0,
            "rotation_deg": 0.0,
            "origin": [0.0, 0.0],
        },

        "levels": levels,
        "areas": areas,
        "walls": walls,
        "columns": columns,
        "obstacles": obstacles,
        "vertical_connections": [],

        "_ingestion_report": {
            "source_dxf": str(DXF_FILE),
            "entities_ignored": ignored,
            "doors_detected": len(doors),
            "doors_assigned": (
                len(doors)
                - len(unassigned_doors)
            ),
            "doors_unassigned": unassigned_doors,
        },
    }

    return model


# ============================================================
# MAIN
# ============================================================

def main():
    print(
        "Viswalk DXF Ingestion v0.1"
    )
    print("=" * 60)

    print("Reading:")
    print(DXF_FILE)

    doc = read_dxf(
        DXF_FILE
    )

    model = ingest(
        doc
    )

    report = model[
        "_ingestion_report"
    ]

    print()
    print("DXF ingestion summary:")
    print(
        "Levels:",
        len(model["levels"]),
    )
    print(
        "Areas:",
        len(model["areas"]),
    )
    print(
        "Walls:",
        len(model["walls"]),
    )
    print(
        "Columns:",
        len(model["columns"]),
    )
    print(
        "Obstacles:",
        len(model["obstacles"]),
    )
    print(
        "Doors detected:",
        report["doors_detected"],
    )
    print(
        "Doors assigned:",
        report["doors_assigned"],
    )
    print(
        "Doors unassigned:",
        len(
            report["doors_unassigned"]
        ),
    )

    with OUTPUT_JSON.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            model,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print("SUCCESS")
    print("Generated JSON:")
    print(OUTPUT_JSON)


if __name__ == "__main__":
    main()
