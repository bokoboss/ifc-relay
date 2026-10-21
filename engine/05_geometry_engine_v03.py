import json
import math
from pathlib import Path

import win32com.client as com

from shapely.geometry import (
    Polygon,
    MultiPolygon,
    GeometryCollection,
    LineString,
    Point,
    box,
)
from shapely.ops import unary_union
from shapely.affinity import rotate, scale as scale_geometry, translate
from shapely.validation import explain_validity
from shapely import to_wkt


# ============================================================
# CONFIG
# ============================================================

ENGINE_VERSION = "0.3"
PROG_ID = "VISSIM.Vissim.2025"

PROJECT_DIR = Path(__file__).resolve().parent
SOURCE_FILE = PROJECT_DIR / "base_empty.inpx"
JSON_FILE = PROJECT_DIR / "geometry_v03.json"

OUTPUT_DIR = PROJECT_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "geometry_engine_v03.inpx"
REPORT_FILE = OUTPUT_DIR / "geometry_engine_v03_report.json"

TOLERANCE = 1e-6


# ============================================================
# BASIC UTILITIES
# ============================================================

def load_json(path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def valid_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_point(point, label):
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError(f"{label}: coordinate must be [x, y]")
    x, y = point
    if not valid_number(x) or not valid_number(y):
        raise ValueError(f"{label}: invalid coordinate {point}")
    return float(x), float(y)


def positive_float(value, label):
    value = float(value)
    if value <= 0:
        raise ValueError(f"{label} must be > 0.")
    return value


# ============================================================
# POLYGON NORMALIZATION
# ============================================================

def polygonal_only(geometry):
    if geometry.is_empty:
        raise ValueError("Geometry is empty.")

    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry])

    if isinstance(geometry, MultiPolygon):
        return geometry

    if isinstance(geometry, GeometryCollection):
        polygons = []
        for part in geometry.geoms:
            if isinstance(part, Polygon):
                polygons.append(part)
            elif isinstance(part, MultiPolygon):
                polygons.extend(list(part.geoms))

        if not polygons:
            raise ValueError("No polygonal geometry found.")

        return polygonal_only(unary_union(polygons))

    raise ValueError(f"Unsupported geometry type: {geometry.geom_type}")


def validate_geometry(geometry, label):
    if geometry.is_empty:
        raise ValueError(f"{label}: geometry is empty.")

    if not geometry.is_valid:
        raise ValueError(
            f"{label}: invalid geometry: {explain_validity(geometry)}"
        )

    if geometry.area <= TOLERANCE:
        raise ValueError(f"{label}: area is zero.")

    return geometry


# ============================================================
# TRANSFORM
# ============================================================

def apply_transform(geometry, transform):
    scale_factor = float(transform.get("scale", 1.0))
    if scale_factor <= 0:
        raise ValueError("transform.scale must be > 0.")

    rotation_deg = float(transform.get("rotation_deg", 0.0))
    ox, oy = validate_point(
        transform.get("origin", [0.0, 0.0]),
        "transform.origin",
    )

    geometry = scale_geometry(
        geometry,
        xfact=scale_factor,
        yfact=scale_factor,
        origin=(0, 0),
    )
    geometry = rotate(
        geometry,
        rotation_deg,
        origin=(0, 0),
        use_radians=False,
    )
    geometry = translate(
        geometry,
        xoff=ox,
        yoff=oy,
    )
    return geometry


# ============================================================
# LEVELS
# ============================================================

def build_levels(data):
    records = []
    seen = set()

    for item in data.get("levels", []):
        key = int(item["key"])
        if key <= 0:
            raise ValueError(f"Invalid Level key: {key}")
        if key in seen:
            raise ValueError(f"Duplicate Level key: {key}")
        seen.add(key)

        z = float(item["z"])
        name = item.get("name", f"Level {key}")

        records.append({
            "key": key,
            "name": name,
            "z": z,
        })

    if not records:
        raise ValueError("At least one Level is required.")

    return records


# ============================================================
# 3D PROPERTIES
# ============================================================

def build_3d_properties(item, object_type, defaults):
    if object_type == "wall":
        default_height = defaults.get("wall_height", 3.0)
    elif object_type == "column":
        default_height = defaults.get("column_height", 3.0)
    else:
        default_height = defaults.get("obstacle_height", 1.0)

    height = float(item.get("height", default_height))
    if height <= 0:
        raise ValueError(f"{object_type} height must be > 0.")

    z_offset = float(
        item.get(
            "z_offset",
            defaults.get("z_offset", 0.0),
        )
    )

    level_key = item.get(
        "level_key",
        defaults.get("level_key", 1),
    )
    if level_key is not None:
        level_key = int(level_key)
        if level_key <= 0:
            raise ValueError("level_key must be > 0.")

    return {
        "height": height,
        "z_offset": z_offset,
        "level_key": level_key,
    }


# ============================================================
# AREA
# ============================================================

def build_area(item):
    key = int(item["key"])
    name = item.get("name", f"Area {key}")

    points = [
        validate_point(point, f"Area {key}")
        for point in item["polygon"]
    ]

    if len(points) < 3:
        raise ValueError(f"Area {key}: requires at least 3 points.")

    geometry = Polygon(points)
    validate_geometry(geometry, f"Area {key} ({name})")
    return geometry


# ============================================================
# WALL + OPENINGS
# ============================================================

def build_opening_polygon(start, end, thickness, opening):
    sx, sy = start
    ex, ey = end

    cx, cy = validate_point(
        opening["center"],
        "opening.center",
    )
    width = positive_float(
        opening["width"],
        "opening.width",
    )

    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)

    if length <= TOLERANCE:
        raise ValueError("Wall has zero length.")

    ux = dx / length
    uy = dy / length

    px = -uy
    py = ux

    half_width = width / 2.0
    half_depth = thickness / 2.0 + 0.05

    return Polygon([
        (
            cx - ux * half_width - px * half_depth,
            cy - uy * half_width - py * half_depth,
        ),
        (
            cx + ux * half_width - px * half_depth,
            cy + uy * half_width - py * half_depth,
        ),
        (
            cx + ux * half_width + px * half_depth,
            cy + uy * half_width + py * half_depth,
        ),
        (
            cx - ux * half_width + px * half_depth,
            cy - uy * half_width + py * half_depth,
        ),
    ])


def build_wall(item):
    key = int(item["key"])
    name = item.get("name", f"Wall {key}")

    start = validate_point(item["start"], f"Wall {key}.start")
    end = validate_point(item["end"], f"Wall {key}.end")
    thickness = positive_float(
        item["thickness"],
        f"Wall {key}.thickness",
    )

    line = LineString([start, end])
    if line.length <= TOLERANCE:
        raise ValueError(f"Wall {key}: wall length is zero.")

    geometry = line.buffer(
        thickness / 2.0,
        cap_style=2,
        join_style=2,
    )

    openings = item.get("openings", [])
    if openings:
        cutters = [
            build_opening_polygon(
                start,
                end,
                thickness,
                opening,
            )
            for opening in openings
        ]
        geometry = geometry.difference(
            unary_union(cutters)
        )

    geometry = polygonal_only(geometry)
    validate_geometry(
        geometry,
        f"Wall {key} ({name})",
    )
    return geometry


# ============================================================
# COLUMN
# ============================================================

def build_column(item):
    key = int(item["key"])
    name = item.get("name", f"Column {key}")

    cx, cy = validate_point(
        item["center"],
        f"Column {key}.center",
    )

    shape = (
        item.get("shape", "rectangle")
        .lower()
        .strip()
    )

    if shape == "rectangle":
        width = positive_float(
            item["width"],
            f"Column {key}.width",
        )
        depth = positive_float(
            item["depth"],
            f"Column {key}.depth",
        )

        geometry = box(
            cx - width / 2.0,
            cy - depth / 2.0,
            cx + width / 2.0,
            cy + depth / 2.0,
        )

        rotation_deg = float(
            item.get("rotation_deg", 0.0)
        )
        if abs(rotation_deg) > TOLERANCE:
            geometry = rotate(
                geometry,
                rotation_deg,
                origin=(cx, cy),
                use_radians=False,
            )

    elif shape == "circle":
        diameter = positive_float(
            item["diameter"],
            f"Column {key}.diameter",
        )
        geometry = Point(
            cx,
            cy,
        ).buffer(
            diameter / 2.0,
            quad_segs=16,
        )

    else:
        raise ValueError(
            f"Column {key}: unsupported shape '{shape}'."
        )

    validate_geometry(
        geometry,
        f"Column {key} ({name})",
    )
    return geometry


# ============================================================
# RAW OBSTACLE
# ============================================================

def build_raw_obstacle(item):
    key = int(item["key"])
    name = item.get("name", f"Obstacle {key}")

    points = [
        validate_point(point, f"Obstacle {key}")
        for point in item["polygon"]
    ]

    if len(points) < 3:
        raise ValueError(
            f"Obstacle {key}: requires at least 3 points."
        )

    geometry = Polygon(points)
    validate_geometry(
        geometry,
        f"Obstacle {key} ({name})",
    )
    return geometry


# ============================================================
# VERTICAL CONNECTION
# ============================================================

# Vissim accepts a ramp/stair only if its polygon is a rectangle, and it is
# strict about it. Corners of a rotated flight written with 4 decimals
# (vissim_wkt) are no longer exactly perpendicular, so Vissim refuses them
# ("Ramp has to be a rectangle"). Rebuild the rectangle on the same 0.1 mm
# grid with integer side vectors u = (p, q) and w = (-q, p): perpendicular
# exactly, whatever the rounding.
RAMP_GRID = 1e-4
RAMP_MAX_VECTOR = 150          # |u| in grid units: angle vs length resolution


def exact_rectangle(geometry):
    coords = list(geometry.exterior.coords)[:4]
    (x0, y0), (x1, y1), _, (x3, y3) = coords
    ex, ey = x1 - x0, y1 - y0
    fx, fy = x3 - x0, y3 - y0
    length = math.hypot(ex, ey)
    width = math.hypot(fx, fy)
    if length <= 0 or width <= 0:
        return geometry
    angle = math.atan2(ey, ex)
    side = 1 if ex * fy - ey * fx >= 0 else -1
    best = None
    candidates = set()
    for r in range(1, RAMP_MAX_VECTOR + 1):
        cp, cq = r * math.cos(angle), r * math.sin(angle)
        for p in (math.floor(cp), math.ceil(cp)):
            for q in (math.floor(cq), math.ceil(cq)):
                candidates.add((p, q))
    for p, q in sorted(candidates):
        if True:
            norm = math.hypot(p, q)
            if norm < 1 or norm > RAMP_MAX_VECTOR or math.gcd(abs(p), abs(q)) != 1:
                continue
            turn = abs((math.atan2(q, p) - angle + math.pi) % (2 * math.pi) - math.pi)
            if turn > 0.05:
                continue
            step = norm * RAMP_GRID
            m = max(1, round(length / step))
            k = max(1, round(width / step))
            score = turn * max(length, width) + abs(m * step - length) + abs(k * step - width)
            if best is None or score < best[0]:
                best = (score, p, q, m, k)
    if best is None:
        return geometry
    _, p, q, m, k = best
    i0, j0 = round(x0 / RAMP_GRID), round(y0 / RAMP_GRID)
    wp, wq = -q * side, p * side
    corners = [
        (i0, j0),
        (i0 + m * p, j0 + m * q),
        (i0 + m * p + k * wp, j0 + m * q + k * wq),
        (i0 + k * wp, j0 + k * wq),
    ]
    return Polygon([(i * RAMP_GRID, j * RAMP_GRID) for i, j in corners])


def build_vertical_connection(item, transform):
    key = int(item["key"])
    name = item.get(
        "name",
        f"Vertical Connection {key}",
    )

    conn_type = (
        item.get("type", "ramp")
        .lower()
        .strip()
    )

    type_map = {
        "ramp": "RAMP",
        "stairway": "STAIRWAY",
        "stair": "STAIRWAY",
    }

    if conn_type not in type_map:
        raise ValueError(
            f"Vertical connection {key}: "
            f"unsupported type '{conn_type}'."
        )

    points = [
        validate_point(
            point,
            f"Vertical Connection {key}",
        )
        for point in item["polygon"]
    ]

    if len(points) < 3:
        raise ValueError(
            f"Vertical Connection {key}: "
            "requires at least 3 points."
        )

    geometry = Polygon(points)
    validate_geometry(
        geometry,
        f"Vertical Connection {key} ({name})",
    )

    geometry = apply_transform(
        geometry,
        transform,
    )
    if len(points) == 4:
        geometry = exact_rectangle(geometry)

    start_level = int(
        item["start_level"]
    )
    end_level = int(
        item["end_level"]
    )

    if start_level <= 0 or end_level <= 0:
        raise ValueError(
            f"Vertical Connection {key}: "
            "level keys must be > 0."
        )

    if start_level == end_level:
        raise ValueError(
            f"Vertical Connection {key}: "
            "start_level and end_level "
            "must be different."
        )

    record = {
        "key": key,
        "name": name,
        "type": type_map[conn_type],
        "geometry": polygonal_only(geometry),
        "start_level": start_level,
        "end_level": end_level,
        "start_z_offset": float(
            item.get(
                "start_z_offset",
                0.0,
            )
        ),
        "end_z_offset": float(
            item.get(
                "end_z_offset",
                0.0,
            )
        ),
        "thickness": float(
            item.get(
                "thickness",
                0.20,
            )
        ),
        "show_balustrade": bool(
            item.get(
                "show_balustrade",
                True,
            )
        ),
    }

    if record["thickness"] <= 0:
        raise ValueError(
            f"Vertical Connection {key}: "
            "thickness must be > 0."
        )

    if record["type"] == "STAIRWAY":
        steps = int(
            item.get("steps", 0)
        )
        if steps <= 0:
            raise ValueError(
                f"Stairway {key}: "
                "steps must be > 0."
            )
        record["steps"] = steps

    return record


# ============================================================
# WKT
# ============================================================

def vissim_wkt(geometry):
    geometry = polygonal_only(geometry)

    return to_wkt(
        geometry,
        rounding_precision=4,
        trim=False,
        output_dimension=2,
    )


# ============================================================
# SEMANTIC MODEL
# ============================================================

def build_geometry_model(data):
    transform = data.get(
        "transform",
        {},
    )
    defaults = data.get(
        "defaults",
        {},
    )

    levels = build_levels(data)
    level_keys = {
        record["key"]
        for record in levels
    }

    area_records = []
    obstacle_records = []
    vertical_records = []

    # --------------------------------------------------------
    # AREAS
    # --------------------------------------------------------

    area_keys = set()

    for item in data.get(
        "areas",
        [],
    ):
        key = int(item["key"])

        if key <= 0:
            raise ValueError(
                f"Invalid Area key: {key}"
            )
        if key in area_keys:
            raise ValueError(
                f"Duplicate Area key: {key}"
            )
        area_keys.add(key)

        level_key = int(
            item.get(
                "level_key",
                defaults.get(
                    "level_key",
                    1,
                ),
            )
        )

        if level_key not in level_keys:
            raise ValueError(
                f"Area {key}: "
                f"Level {level_key} "
                "is not defined."
            )

        geometry = apply_transform(
            build_area(item),
            transform,
        )

        area_records.append({
            "key": key,
            "name": item.get(
                "name",
                f"Area {key}",
            ),
            "type": "area",
            "level_key": level_key,
            "geometry": polygonal_only(
                geometry
            ),
        })

    # --------------------------------------------------------
    # OBSTACLES
    # --------------------------------------------------------

    obstacle_keys = set()

    source_groups = [
        (
            "wall",
            data.get("walls", []),
            build_wall,
        ),
        (
            "column",
            data.get("columns", []),
            build_column,
        ),
        (
            "obstacle",
            data.get("obstacles", []),
            build_raw_obstacle,
        ),
    ]

    for (
        object_type,
        items,
        builder,
    ) in source_groups:
        for item in items:
            key = int(item["key"])

            if key <= 0:
                raise ValueError(
                    f"Invalid obstacle key: {key}"
                )

            if key in obstacle_keys:
                raise ValueError(
                    "Duplicate semantic "
                    f"obstacle key: {key}"
                )

            obstacle_keys.add(key)

            geometry = apply_transform(
                builder(item),
                transform,
            )

            props = build_3d_properties(
                item,
                object_type,
                defaults,
            )

            if props["level_key"] not in level_keys:
                raise ValueError(
                    f"{object_type} {key}: "
                    f"Level {props['level_key']} "
                    "is not defined."
                )

            obstacle_records.append({
                "key": key,
                "name": item.get(
                    "name",
                    f"{object_type} {key}",
                ),
                "type": object_type,
                "geometry": polygonal_only(
                    geometry
                ),
                **props,
            })

    # --------------------------------------------------------
    # VERTICAL CONNECTIONS
    # --------------------------------------------------------

    vertical_keys = set()

    for item in data.get(
        "vertical_connections",
        [],
    ):
        record = build_vertical_connection(
            item,
            transform,
        )

        key = record["key"]

        if key in vertical_keys:
            raise ValueError(
                "Duplicate vertical "
                f"connection key: {key}"
            )

        vertical_keys.add(key)

        if record["start_level"] not in level_keys:
            raise ValueError(
                f"Vertical Connection {key}: "
                f"start Level "
                f"{record['start_level']} "
                "is not defined."
            )

        if record["end_level"] not in level_keys:
            raise ValueError(
                f"Vertical Connection {key}: "
                f"end Level "
                f"{record['end_level']} "
                "is not defined."
            )

        vertical_records.append(record)

    return (
        levels,
        area_records,
        obstacle_records,
        vertical_records,
    )


# ============================================================
# OBSTACLE OVERLAP (F-16)
# ============================================================

def find_obstacle_overlaps(
    obstacles,
):
    """Same-level obstacle pairs that overlap by more than TOLERANCE.

    Same result, in the same order (i < j, ascending), as checking every pair,
    but obstacles are grouped by level and only pairs whose bounding boxes
    meet (Shapely STRtree) are intersected: an overlap with area > 0 needs
    the boxes to meet, so no pair is missed.
    """
    from shapely import STRtree

    by_level = {}
    for index, record in enumerate(obstacles):
        by_level.setdefault(
            record["level_key"], []
        ).append(index)

    trees = {
        level_key: (
            STRtree([obstacles[n]["geometry"] for n in members]),
            members,
        )
        for level_key, members in by_level.items()
    }

    found = []
    for i, a in enumerate(obstacles):
        tree, members = trees[a["level_key"]]
        candidates = sorted(
            members[n]
            for n in tree.query(a["geometry"])
            if members[n] > i
        )
        for j in candidates:
            b = obstacles[j]
            overlap = a["geometry"].intersection(
                b["geometry"]
            )
            if (
                not overlap.is_empty
                and overlap.area
                > TOLERANCE
            ):
                found.append({
                    "type":
                        "obstacle_overlap",
                    "level_key":
                        a["level_key"],
                    "objects": [
                        a["key"],
                        b["key"],
                    ],
                    "names": [
                        a["name"],
                        b["name"],
                    ],
                    "overlap_area_m2":
                        round(
                            overlap.area,
                            6,
                        ),
                })
    return found


# ============================================================
# ENGINEERING VALIDATION
# ============================================================

def validate_model(
    levels,
    areas,
    obstacles,
    vertical_connections,
):
    warnings = []

    level_keys = {
        level["key"]
        for level in levels
    }

    # --------------------------------------------------------
    # BUILD WALKABLE UNION BY LEVEL
    # --------------------------------------------------------

    walkable_by_level = {}

    for level_key in level_keys:
        geoms = [
            record["geometry"]
            for record in areas
            if record["level_key"]
            == level_key
        ]

        if geoms:
            walkable_by_level[level_key] = (
                unary_union(geoms)
            )
        else:
            warnings.append({
                "type":
                    "level_without_walkable_area",
                "level_key":
                    level_key,
            })

    # --------------------------------------------------------
    # OBSTACLE OUTSIDE AREA - SAME LEVEL ONLY
    # --------------------------------------------------------

    for record in obstacles:
        level_key = record["level_key"]

        walkable = walkable_by_level.get(
            level_key
        )

        if walkable is None:
            continue

        outside = record[
            "geometry"
        ].difference(
            walkable
        )

        if (
            not outside.is_empty
            and outside.area
            > TOLERANCE
        ):
            warnings.append({
                "type":
                    "obstacle_outside_walkable",
                "key":
                    record["key"],
                "name":
                    record["name"],
                "level_key":
                    level_key,
                "outside_area_m2":
                    round(
                        outside.area,
                        6,
                    ),
            })

    # --------------------------------------------------------
    # OBSTACLE OVERLAP - SAME LEVEL ONLY
    # --------------------------------------------------------

    warnings.extend(
        find_obstacle_overlaps(
            obstacles
        )
    )

    # --------------------------------------------------------
    # VERTICAL CONNECTION FOOTPRINT CHECK
    # --------------------------------------------------------

    for record in vertical_connections:
        start_walkable = (
            walkable_by_level.get(
                record["start_level"]
            )
        )
        end_walkable = (
            walkable_by_level.get(
                record["end_level"]
            )
        )

        if start_walkable is not None:
            overlap = (
                record["geometry"]
                .intersection(
                    start_walkable
                )
            )
            if (
                overlap.is_empty
                or overlap.area
                <= TOLERANCE
            ):
                warnings.append({
                    "type":
                        "vertical_connection_not_on_start_area",
                    "key":
                        record["key"],
                    "name":
                        record["name"],
                    "start_level":
                        record["start_level"],
                })

        if end_walkable is not None:
            overlap = (
                record["geometry"]
                .intersection(
                    end_walkable
                )
            )
            if (
                overlap.is_empty
                or overlap.area
                <= TOLERANCE
            ):
                warnings.append({
                    "type":
                        "vertical_connection_not_on_end_area",
                    "key":
                        record["key"],
                    "name":
                        record["name"],
                    "end_level":
                        record["end_level"],
                })

    return warnings


# ============================================================
# VISSIM OBSTACLE FRAGMENTATION
# ============================================================

def prepare_vissim_obstacles(
    obstacles,
):
    if not obstacles:
        return []

    declared_keys = {
        int(record["key"])
        for record in obstacles
    }

    used_keys = set()
    next_generated_key = (
        max(declared_keys) + 1
    )

    results = []

    for record in obstacles:
        source_key = int(
            record["key"]
        )

        geometry = polygonal_only(
            record["geometry"]
        )

        parts = list(
            geometry.geoms
        )

        parts.sort(
            key=lambda g: (
                round(
                    g.centroid.x,
                    8,
                ),
                round(
                    g.centroid.y,
                    8,
                ),
            )
        )

        part_count = len(parts)

        for index, part in enumerate(
            parts,
            start=1,
        ):
            validate_geometry(
                part,
                (
                    f"{record['name']} "
                    f"part {index}"
                ),
            )

            if len(part.interiors) > 0:
                raise ValueError(
                    f"{record['name']} "
                    f"part {index}: "
                    "Vissim obstacle polygon "
                    "contains an interior ring."
                )

            if (
                index == 1
                and source_key
                not in used_keys
            ):
                vissim_key = source_key
            else:
                while (
                    next_generated_key
                    in declared_keys
                    or next_generated_key
                    in used_keys
                ):
                    next_generated_key += 1

                vissim_key = (
                    next_generated_key
                )
                next_generated_key += 1

            used_keys.add(
                vissim_key
            )

            if part_count == 1:
                name = record["name"]
            else:
                name = (
                    f"{record['name']} "
                    f"[part "
                    f"{index}/{part_count}]"
                )

            results.append({
                "key":
                    vissim_key,
                "source_key":
                    source_key,
                "source_name":
                    record["name"],
                "name":
                    name,
                "type":
                    record["type"],
                "part_index":
                    index,
                "part_count":
                    part_count,
                "geometry":
                    MultiPolygon([part]),
                "height":
                    record["height"],
                "z_offset":
                    record["z_offset"],
                "level_key":
                    record["level_key"],
            })

    return results


# ============================================================
# COM HELPERS
# ============================================================

def safe_set(obj, attr, value):
    obj.SetAttValue(
        attr,
        value,
    )


def safe_read(obj, attr):
    try:
        return obj.AttValue(attr)
    except Exception as exc:
        return f"<ERROR: {exc}>"


# ============================================================
# SEND TO VISSIM
# ============================================================

def send_to_vissim(
    levels,
    areas,
    obstacles,
    vertical_connections,
):
    print(
        f"\nConnecting to Vissim ({PROG_ID})..."
    )

    vissim = (
        com.gencache.EnsureDispatch(
            PROG_ID
        )
    )

    try:
        print(
            "Loading base network:"
        )
        print(SOURCE_FILE)

        vissim.LoadNet(
            str(SOURCE_FILE)
        )

        level_container = (
            vissim.Net.Levels
        )
        area_container = (
            vissim.Net.Areas
        )
        obstacle_container = (
            vissim.Net.Obstacles
        )
        ramp_container = (
            vissim.Net.Ramps
        )

        # ----------------------------------------------------
        # LEVELS FIRST
        # ----------------------------------------------------

        print(
            "\nCreating / configuring Levels..."
        )

        for record in levels:
            key = record["key"]

            if level_container.ItemKeyExists(
                key
            ):
                obj = level_container.ItemByKey(
                    key
                )
                action = "Configure"
            else:
                obj = level_container.AddLevel(
                    key
                )
                action = "Create"

            safe_set(
                obj,
                "Name",
                record["name"],
            )
            safe_set(
                obj,
                "zCoord",
                record["z"],
            )

            print(
                f"  {action} Level "
                f"{key}: {record['name']} "
                f"| z={record['z']:.2f} m"
            )

        # ----------------------------------------------------
        # AREAS
        # ----------------------------------------------------

        print(
            "\nCreating Areas..."
        )

        for record in areas:
            key = record["key"]

            if area_container.ItemKeyExists(
                key
            ):
                raise RuntimeError(
                    f"Area key {key} "
                    "already exists."
                )

            obj = area_container.AddArea(
                key,
                vissim_wkt(
                    record["geometry"]
                ),
            )

            safe_set(
                obj,
                "Name",
                record["name"],
            )
            safe_set(
                obj,
                "Level",
                record["level_key"],
            )

            print(
                f"  Area {key}: "
                f"{record['name']} "
                f"| Level={record['level_key']}"
            )

        # ----------------------------------------------------
        # OBSTACLES
        # ----------------------------------------------------

        print(
            "\nCreating Obstacles..."
        )

        for record in obstacles:
            key = record["key"]

            if obstacle_container.ItemKeyExists(
                key
            ):
                raise RuntimeError(
                    f"Obstacle key {key} "
                    "already exists."
                )

            obj = (
                obstacle_container
                .AddObstacle(
                    key,
                    vissim_wkt(
                        record["geometry"]
                    ),
                )
            )

            safe_set(
                obj,
                "Name",
                record["name"],
            )
            safe_set(
                obj,
                "Level",
                record["level_key"],
            )
            safe_set(
                obj,
                "Height",
                float(
                    record["height"]
                ),
            )
            safe_set(
                obj,
                "zOffsetB",
                float(
                    record["z_offset"]
                ),
            )

            print(
                f"  {record['type']} "
                f"{key}: "
                f"{record['name']} "
                f"| Level="
                f"{record['level_key']} "
                f"| H="
                f"{record['height']:.2f} m"
            )

        # ----------------------------------------------------
        # VERTICAL CONNECTIONS
        # ----------------------------------------------------

        print(
            "\nCreating Vertical Connections..."
        )

        for record in vertical_connections:
            key = record["key"]

            if ramp_container.ItemKeyExists(
                key
            ):
                raise RuntimeError(
                    "Ramp/Stair key "
                    f"{key} already exists."
                )

            obj = ramp_container.AddRamp(
                key,
                vissim_wkt(
                    record["geometry"]
                ),
            )

            safe_set(
                obj,
                "Name",
                record["name"],
            )
            safe_set(
                obj,
                "StartLvl",
                record["start_level"],
            )
            safe_set(
                obj,
                "EndLvl",
                record["end_level"],
            )
            safe_set(
                obj,
                "StartZOffset",
                record[
                    "start_z_offset"
                ],
            )
            safe_set(
                obj,
                "EndZOffset",
                record[
                    "end_z_offset"
                ],
            )
            safe_set(
                obj,
                "Type",
                record["type"],
            )
            safe_set(
                obj,
                "Thickness",
                record["thickness"],
            )
            safe_set(
                obj,
                "ShowBalustr",
                record[
                    "show_balustrade"
                ],
            )

            if (
                record["type"]
                == "STAIRWAY"
            ):
                safe_set(
                    obj,
                    "Steps",
                    record["steps"],
                )

            print(
                f"  {record['type']} "
                f"{key}: "
                f"{record['name']} "
                f"| "
                f"{record['start_level']}"
                f" -> "
                f"{record['end_level']}"
            )

        # ----------------------------------------------------
        # VERIFY
        # ----------------------------------------------------

        print()
        print("=" * 60)
        print("VERIFY LEVELS")
        print("=" * 60)

        for obj in level_container.GetAll():
            print(
                f"#{obj.AttValue('No')} "
                f"{obj.AttValue('Name')} "
                f"| z="
                f"{obj.AttValue('zCoord')}"
            )

        print()
        print("=" * 60)
        print("VERIFY VERTICAL CONNECTIONS")
        print("=" * 60)

        for record in vertical_connections:
            obj = ramp_container.ItemByKey(
                record["key"]
            )

            print(
                f"#{record['key']} "
                f"{record['name']} "
                f"| Type="
                f"{safe_read(obj, 'Type')} "
                f"| "
                f"{safe_read(obj, 'StartLvl')}"
                f" -> "
                f"{safe_read(obj, 'EndLvl')} "
                f"| H="
                f"{safe_read(obj, 'Height')} "
                f"| Length3D="
                f"{safe_read(obj, 'Length3D')}"
            )

        print()
        print(
            "Final Levels:",
            level_container.Count,
        )
        print(
            "Final Areas:",
            area_container.Count,
        )
        print(
            "Final Obstacles:",
            obstacle_container.Count,
        )
        print(
            "Final Ramps/Stairs:",
            ramp_container.Count,
        )

        print(
            "\nSaving:"
        )
        print(OUTPUT_FILE)

        vissim.SaveNetAs(
            str(OUTPUT_FILE)
        )

        print(
            "\nVissim model saved."
        )

        input(
            "\nPress Enter "
            "to close Vissim..."
        )

    finally:
        try:
            vissim.Exit()
        except Exception:
            pass


# ============================================================
# REPORT
# ============================================================

def write_report(
    levels,
    areas,
    semantic_obstacles,
    vissim_obstacles,
    vertical_connections,
    warnings,
):
    report = {
        "engine_version":
            ENGINE_VERSION,
        "source_file":
            str(SOURCE_FILE),
        "summary": {
            "levels":
                len(levels),
            "areas":
                len(areas),
            "semantic_obstacles":
                len(
                    semantic_obstacles
                ),
            "vissim_obstacles":
                len(
                    vissim_obstacles
                ),
            "vertical_connections":
                len(
                    vertical_connections
                ),
            "warnings":
                len(warnings),
        },
        "levels":
            levels,
        "areas":
            [],
        "semantic_obstacles":
            [],
        "vissim_obstacles":
            [],
        "vertical_connections":
            [],
        "warnings":
            warnings,
    }

    for record in areas:
        geometry = record["geometry"]

        report["areas"].append({
            "key":
                record["key"],
            "name":
                record["name"],
            "level_key":
                record["level_key"],
            "area_m2":
                round(
                    geometry.area,
                    6,
                ),
            "wkt":
                vissim_wkt(
                    geometry
                ),
        })

    for record in semantic_obstacles:
        geometry = record["geometry"]

        report[
            "semantic_obstacles"
        ].append({
            "key":
                record["key"],
            "name":
                record["name"],
            "type":
                record["type"],
            "level_key":
                record["level_key"],
            "height":
                record["height"],
            "z_offset":
                record["z_offset"],
            "polygon_parts":
                len(
                    polygonal_only(
                        geometry
                    ).geoms
                ),
            "area_m2":
                round(
                    geometry.area,
                    6,
                ),
            "wkt":
                vissim_wkt(
                    geometry
                ),
        })

    for record in vissim_obstacles:
        geometry = record["geometry"]

        report[
            "vissim_obstacles"
        ].append({
            "key":
                record["key"],
            "source_key":
                record["source_key"],
            "source_name":
                record["source_name"],
            "name":
                record["name"],
            "type":
                record["type"],
            "level_key":
                record["level_key"],
            "height":
                record["height"],
            "z_offset":
                record["z_offset"],
            "part_index":
                record["part_index"],
            "part_count":
                record["part_count"],
            "area_m2":
                round(
                    geometry.area,
                    6,
                ),
            "wkt":
                vissim_wkt(
                    geometry
                ),
        })

    for record in vertical_connections:
        geometry = record["geometry"]

        report[
            "vertical_connections"
        ].append({
            "key":
                record["key"],
            "name":
                record["name"],
            "type":
                record["type"],
            "start_level":
                record[
                    "start_level"
                ],
            "end_level":
                record[
                    "end_level"
                ],
            "start_z_offset":
                record[
                    "start_z_offset"
                ],
            "end_z_offset":
                record[
                    "end_z_offset"
                ],
            "steps":
                record.get(
                    "steps"
                ),
            "thickness":
                record["thickness"],
            "area_m2":
                round(
                    geometry.area,
                    6,
                ),
            "wkt":
                vissim_wkt(
                    geometry
                ),
        })

    with REPORT_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            report,
            f,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not SOURCE_FILE.exists():
        raise FileNotFoundError(
            "base_empty.inpx "
            f"not found: {SOURCE_FILE}"
        )

    if not JSON_FILE.exists():
        raise FileNotFoundError(
            "Geometry JSON "
            f"not found: {JSON_FILE}"
        )

    print(
        "Viswalk Geometry Engine v0.3"
    )
    print("=" * 60)
    print("Base network:")
    print(SOURCE_FILE)

    data = load_json(
        JSON_FILE
    )

    units = (
        data.get(
            "project",
            {},
        )
        .get(
            "units",
            "m",
        )
    )

    if units != "m":
        raise ValueError(
            "v0.3 requires "
            "project.units = 'm'."
        )

    (
        levels,
        areas,
        semantic_obstacles,
        vertical_connections,
    ) = build_geometry_model(
        data
    )

    warnings = validate_model(
        levels,
        areas,
        semantic_obstacles,
        vertical_connections,
    )

    vissim_obstacles = (
        prepare_vissim_obstacles(
            semantic_obstacles
        )
    )

    print()
    print("Geometry generated:")
    print("Levels:", len(levels))
    print("Areas:", len(areas))
    print(
        "Semantic Obstacles:",
        len(
            semantic_obstacles
        ),
    )
    print(
        "Vissim Obstacles:",
        len(
            vissim_obstacles
        ),
    )
    print(
        "Vertical Connections:",
        len(
            vertical_connections
        ),
    )
    print(
        "Warnings:",
        len(warnings),
    )

    if warnings:
        print(
            "\nVALIDATION WARNINGS"
        )
        for warning in warnings:
            print(
                "-",
                warning,
            )
    else:
        print(
            "\nGeometry validation: PASS"
        )

    source_keys_shown = set()

    for record in vissim_obstacles:
        if record["part_count"] <= 1:
            continue

        source_key = record[
            "source_key"
        ]

        if source_key in source_keys_shown:
            continue

        source_keys_shown.add(
            source_key
        )

        print(
            f"\nSplit: "
            f"{record['source_name']} "
            f"-> "
            f"{record['part_count']} "
            "Vissim Obstacles"
        )

    write_report(
        levels,
        areas,
        semantic_obstacles,
        vissim_obstacles,
        vertical_connections,
        warnings,
    )

    print("\nReport:")
    print(REPORT_FILE)

    send_to_vissim(
        levels,
        areas,
        vissim_obstacles,
        vertical_connections,
    )

    print()
    print("=" * 60)
    print("SUCCESS")
    print("=" * 60)
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
