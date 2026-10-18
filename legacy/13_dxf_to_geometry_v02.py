import json
import math
import re
from collections import defaultdict
from pathlib import Path

import ezdxf
from ezdxf import units

from shapely.geometry import (
    LineString,
    Point,
    Polygon,
)


# ============================================================
# CONFIG
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent

DXF_FILE = PROJECT_DIR / "sample_floorplan.dxf"
CONFIG_FILE = PROJECT_DIR / "cad_layer_mapping.json"

OUTPUT_JSON = PROJECT_DIR / "geometry_from_dxf_v02.json"
REPORT_FILE = (
    PROJECT_DIR
    / "output"
    / "dxf_ingestion_v02_report.json"
)

TOL = 1e-9


# ============================================================
# GENERIC HELPERS
# ============================================================

def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def point2(v, scale=1.0):
    return [
        float(v.x) * scale,
        float(v.y) * scale,
    ]


def distance(a, b):
    return math.hypot(
        b[0] - a[0],
        b[1] - a[1],
    )


def midpoint(a, b):
    return [
        (a[0] + b[0]) / 2.0,
        (a[1] + b[1]) / 2.0,
    ]


def segment_angle(a, b):
    return (
        math.degrees(
            math.atan2(
                b[1] - a[1],
                b[0] - a[0],
            )
        )
        % 180.0
    )


def angle_difference(a, b):
    diff = abs(a - b) % 180.0
    return min(diff, 180.0 - diff)


def detect_scale_to_meters(doc, config):
    override = config.get("source_units_override")

    manual = {
        "m": 1.0,
        "cm": 0.01,
        "mm": 0.001,
        "km": 1000.0,
        "in": 0.0254,
        "ft": 0.3048,
    }

    if override:
        key = str(override).lower().strip()
        if key not in manual:
            raise ValueError(
                f"Unsupported source_units_override: {override}"
            )
        return manual[key], f"override:{key}"

    source_units = int(doc.units or 0)

    if source_units == 0:
        return (
            float(
                config.get(
                    "unitless_scale_to_meters",
                    1.0,
                )
            ),
            "unitless_config_scale",
        )

    try:
        return (
            float(
                units.conversion_factor(
                    source_units,
                    units.M,
                )
            ),
            f"INSUNITS_{source_units}",
        )
    except Exception:
        return (
            float(
                config.get(
                    "unitless_scale_to_meters",
                    1.0,
                )
            ),
            f"unsupported_INSUNITS_{source_units}",
        )


# ============================================================
# LAYER / BLOCK MAPPING
# ============================================================

def resolve_rule(layer, config):
    layer_upper = layer.upper().strip()

    for rule in config.get("layer_rules", []):
        aliases = {
            str(x).upper()
            for x in rule.get("aliases", [])
        }

        if layer_upper in aliases:
            return {
                "semantic": rule["semantic"],
                "level": int(
                    rule.get(
                        "default_level",
                        config["defaults"].get(
                            "default_level",
                            1,
                        ),
                    )
                ),
            }

        pattern = rule.get("regex")
        if pattern:
            match = re.match(
                pattern,
                layer,
                flags=re.IGNORECASE,
            )
            if match:
                level_text = (
                    match.groupdict().get("level")
                )
                return {
                    "semantic": rule["semantic"],
                    "level": (
                        int(level_text)
                        if level_text
                        else int(
                            config["defaults"].get(
                                "default_level",
                                1,
                            )
                        )
                    ),
                }

    return None


def resolve_block_rule(block_name, config):
    for rule in config.get("block_rules", []):
        pattern = rule.get("regex")
        if pattern and re.search(pattern, block_name):
            return rule["semantic"]
    return None


# ============================================================
# ENTITY FLATTENING
# ============================================================

def flatten_entity(
    entity,
    inherited_layer=None,
    block_semantic=None,
    warnings=None,
    depth=0,
):
    """
    Yield:
      (entity, effective_layer, forced_semantic, source_info)

    INSERT contents are transformed by ezdxf.virtual_entities().
    Entities on layer 0 inherit the INSERT layer.
    """
    if warnings is None:
        warnings = []

    if depth > 8:
        warnings.append({
            "type": "insert_recursion_limit",
            "message": "Nested INSERT depth exceeded 8.",
        })
        return

    etype = entity.dxftype()

    raw_layer = str(
        entity.dxf.get(
            "layer",
            "0",
        )
    )

    effective_layer = raw_layer

    if raw_layer == "0" and inherited_layer:
        effective_layer = inherited_layer

    if etype != "INSERT":
        yield (
            entity,
            effective_layer,
            block_semantic,
            {
                "source_type": etype,
                "source_layer": effective_layer,
            },
        )
        return

    insert_layer = effective_layer
    block_name = str(entity.dxf.name)

    if getattr(entity, "mcount", 1) > 1:
        warnings.append({
            "type": "minsert_not_fully_supported",
            "block": block_name,
            "layer": insert_layer,
            "mcount": int(entity.mcount),
        })

    try:
        children = list(
            entity.virtual_entities()
        )
    except Exception as exc:
        warnings.append({
            "type": "insert_expand_failed",
            "block": block_name,
            "layer": insert_layer,
            "error": str(exc),
        })
        return

    for child in children:
        yield from flatten_entity(
            child,
            inherited_layer=insert_layer,
            block_semantic=block_semantic,
            warnings=warnings,
            depth=depth + 1,
        )


# ============================================================
# ENTITY GEOMETRY
# ============================================================

def line_points(entity, scale):
    start = point2(entity.dxf.start, scale)
    end = point2(entity.dxf.end, scale)
    return start, end


def polyline_points(entity, scale):
    etype = entity.dxftype()

    if etype == "LWPOLYLINE":
        # vertices_in_wcs() is important after INSERT transforms.
        return [
            point2(v, scale)
            for v in entity.vertices_in_wcs()
        ]

    if etype == "POLYLINE":
        points = []

        for vertex in entity.vertices:
            try:
                loc = vertex.dxf.location
                points.append(
                    point2(loc, scale)
                )
            except Exception:
                pass

        return points

    raise ValueError(
        f"Not a supported polyline: {etype}"
    )


def is_closed_polyline(entity):
    etype = entity.dxftype()

    if etype == "LWPOLYLINE":
        return bool(entity.closed)

    if etype == "POLYLINE":
        try:
            return bool(entity.is_closed)
        except Exception:
            try:
                return bool(entity.is_closed_m)
            except Exception:
                return False

    return False


def arc_to_segments(entity, scale, angle_step_deg):
    center = point2(entity.dxf.center, scale)
    radius = float(entity.dxf.radius) * scale
    start_angle = float(entity.dxf.start_angle)
    end_angle = float(entity.dxf.end_angle)

    span = (end_angle - start_angle) % 360.0

    if span <= TOL:
        span = 360.0

    count = max(
        2,
        int(
            math.ceil(
                span / angle_step_deg
            )
        ),
    )

    points = []

    for i in range(count + 1):
        angle = math.radians(
            start_angle
            + span * i / count
        )

        points.append([
            center[0]
            + radius * math.cos(angle),

            center[1]
            + radius * math.sin(angle),
        ])

    return [
        (points[i], points[i + 1])
        for i in range(len(points) - 1)
    ]


# ============================================================
# ORIENTED RECTANGLE
# ============================================================

def oriented_rectangle_properties(points):
    polygon = Polygon(points)

    if not polygon.is_valid:
        polygon = polygon.buffer(0)

    if polygon.is_empty:
        raise ValueError(
            "Could not build polygon."
        )

    rect = polygon.minimum_rotated_rectangle

    coords = list(
        rect.exterior.coords
    )[:-1]

    if len(coords) != 4:
        raise ValueError(
            "Minimum rotated rectangle "
            "did not return 4 vertices."
        )

    edges = []

    for i in range(4):
        a = coords[i]
        b = coords[(i + 1) % 4]

        length = distance(a, b)

        edges.append(
            (
                length,
                a,
                b,
            )
        )

    edges.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    long_length, long_a, long_b = edges[0]
    short_length = edges[-1][0]

    center = [
        float(rect.centroid.x),
        float(rect.centroid.y),
    ]

    angle = segment_angle(
        long_a,
        long_b,
    )

    # Centerline along the longest axis
    ux = math.cos(
        math.radians(angle)
    )
    uy = math.sin(
        math.radians(angle)
    )

    half = long_length / 2.0

    start = [
        center[0] - ux * half,
        center[1] - uy * half,
    ]

    end = [
        center[0] + ux * half,
        center[1] + uy * half,
    ]

    return {
        "center": center,
        "width": long_length,
        "depth": short_length,
        "rotation_deg": angle,
        "centerline_start": start,
        "centerline_end": end,
        "thickness": short_length,
    }


# ============================================================
# DOUBLE-LINE WALL PAIRING
# ============================================================

def projected_overlap_ratio(a1, a2, b1, b2):
    """
    Project both segments onto direction of A and return
    overlap / shorter length.
    """
    dx = a2[0] - a1[0]
    dy = a2[1] - a1[1]

    length_a = math.hypot(dx, dy)

    if length_a <= TOL:
        return 0.0

    ux = dx / length_a
    uy = dy / length_a

    def proj(p):
        return (
            (p[0] - a1[0]) * ux
            + (p[1] - a1[1]) * uy
        )

    a_min, a_max = 0.0, length_a

    bp1 = proj(b1)
    bp2 = proj(b2)

    b_min = min(bp1, bp2)
    b_max = max(bp1, bp2)

    overlap = max(
        0.0,
        min(a_max, b_max)
        - max(a_min, b_min),
    )

    length_b = distance(b1, b2)

    denominator = min(
        length_a,
        length_b,
    )

    if denominator <= TOL:
        return 0.0

    return overlap / denominator


def pair_double_wall_lines(
    raw_lines,
    defaults,
):
    min_gap = float(
        defaults[
            "double_line_wall_min_gap_m"
        ]
    )
    max_gap = float(
        defaults[
            "double_line_wall_max_gap_m"
        ]
    )
    min_overlap = float(
        defaults[
            "double_line_wall_min_overlap_ratio"
        ]
    )
    angle_tol = float(
        defaults[
            "parallel_angle_tolerance_deg"
        ]
    )

    used = set()
    paired = []
    singles = []

    for i, line_a in enumerate(raw_lines):
        if i in used:
            continue

        a1 = line_a["start"]
        a2 = line_a["end"]
        angle_a = segment_angle(a1, a2)

        best = None

        for j in range(
            i + 1,
            len(raw_lines),
        ):
            if j in used:
                continue

            line_b = raw_lines[j]

            if (
                line_a["level_key"]
                != line_b["level_key"]
            ):
                continue

            b1 = line_b["start"]
            b2 = line_b["end"]

            angle_b = segment_angle(
                b1,
                b2,
            )

            if (
                angle_difference(
                    angle_a,
                    angle_b,
                )
                > angle_tol
            ):
                continue

            geom_a = LineString(
                [a1, a2]
            )
            geom_b = LineString(
                [b1, b2]
            )

            gap = geom_a.distance(
                geom_b
            )

            if (
                gap < min_gap
                or gap > max_gap
            ):
                continue

            overlap_ratio = (
                projected_overlap_ratio(
                    a1,
                    a2,
                    b1,
                    b2,
                )
            )

            if overlap_ratio < min_overlap:
                continue

            score = (
                gap,
                -overlap_ratio,
            )

            if (
                best is None
                or score < best[0]
            ):
                best = (
                    score,
                    j,
                    line_b,
                    gap,
                )

        if best is None:
            singles.append(
                line_a
            )
            used.add(i)
            continue

        _, j, line_b, gap = best

        used.add(i)
        used.add(j)

        # Align B endpoint order with A.
        a1 = line_a["start"]
        a2 = line_a["end"]
        b1 = line_b["start"]
        b2 = line_b["end"]

        same = (
            distance(a1, b1)
            + distance(a2, b2)
        )
        reverse = (
            distance(a1, b2)
            + distance(a2, b1)
        )

        if reverse < same:
            b1, b2 = b2, b1

        start = midpoint(a1, b1)
        end = midpoint(a2, b2)

        paired.append({
            "level_key":
                line_a["level_key"],
            "start":
                start,
            "end":
                end,
            "thickness":
                gap,
            "source":
                "double_line_pair",
        })

    return paired, singles


# ============================================================
# MAIN INGESTION
# ============================================================

def ingest(doc, config):
    defaults = config["defaults"]

    scale, scale_basis = (
        detect_scale_to_meters(
            doc,
            config,
        )
    )

    msp = doc.modelspace()

    areas = []
    raw_wall_lines = []
    polygon_walls = []
    door_candidates = []
    columns = []
    obstacles = []
    vertical_connections = []

    warnings = []
    ignored = []
    expanded_inserts = 0

    next_area = 1001
    next_column = 1301
    next_obstacle = 1401
    next_vertical = 2001

    # --------------------------------------------------------
    # Walk modelspace and flatten INSERTs
    # --------------------------------------------------------

    for top_entity in msp:
        top_type = top_entity.dxftype()

        inherited_layer = str(
            top_entity.dxf.get(
                "layer",
                "0",
            )
        )

        forced_semantic = None

        if top_type == "INSERT":
            expanded_inserts += 1

            forced_semantic = (
                resolve_block_rule(
                    str(
                        top_entity.dxf.name
                    ),
                    config,
                )
            )

        for (
            entity,
            layer,
            block_semantic,
            source_info,
        ) in flatten_entity(
            top_entity,
            inherited_layer=inherited_layer,
            block_semantic=forced_semantic,
            warnings=warnings,
        ):
            etype = entity.dxftype()

            rule = resolve_rule(
                layer,
                config,
            )

            semantic = (
                block_semantic
                or (
                    rule["semantic"]
                    if rule
                    else None
                )
            )

            level_key = (
                rule["level"]
                if rule
                else int(
                    defaults.get(
                        "default_level",
                        1,
                    )
                )
            )

            if semantic is None:
                ignored.append({
                    "entity_type": etype,
                    "layer": layer,
                    "reason": "no semantic mapping",
                })
                continue

            # ------------------------------------------------
            # AREA
            # ------------------------------------------------

            if semantic == "area":
                if etype not in {
                    "LWPOLYLINE",
                    "POLYLINE",
                }:
                    warnings.append({
                        "type": "unsupported_area_entity",
                        "entity_type": etype,
                        "layer": layer,
                    })
                    continue

                if not is_closed_polyline(
                    entity
                ):
                    warnings.append({
                        "type": "open_area_polyline",
                        "layer": layer,
                    })
                    continue

                points = polyline_points(
                    entity,
                    scale,
                )

                if len(points) < 3:
                    continue

                areas.append({
                    "key": next_area,
                    "name": f"DXF Area {next_area}",
                    "level_key": level_key,
                    "polygon": points,
                })
                next_area += 1

            # ------------------------------------------------
            # WALL
            # ------------------------------------------------

            elif semantic == "wall":
                if etype == "LINE":
                    start, end = line_points(
                        entity,
                        scale,
                    )

                    raw_wall_lines.append({
                        "level_key":
                            level_key,
                        "start":
                            start,
                        "end":
                            end,
                        "source":
                            "line",
                    })

                elif etype in {
                    "LWPOLYLINE",
                    "POLYLINE",
                }:
                    points = polyline_points(
                        entity,
                        scale,
                    )

                    if is_closed_polyline(
                        entity
                    ):
                        if len(points) >= 3:
                            polygon_walls.append({
                                "level_key":
                                    level_key,
                                "points":
                                    points,
                            })
                    else:
                        # Open polyline becomes a chain of wall lines.
                        for i in range(
                            len(points) - 1
                        ):
                            if distance(
                                points[i],
                                points[i + 1],
                            ) > TOL:
                                raw_wall_lines.append({
                                    "level_key":
                                        level_key,
                                    "start":
                                        points[i],
                                    "end":
                                        points[i + 1],
                                    "source":
                                        "polyline_segment",
                                })

                elif etype == "ARC":
                    for start, end in arc_to_segments(
                        entity,
                        scale,
                        float(
                            defaults[
                                "arc_segment_angle_deg"
                            ]
                        ),
                    ):
                        raw_wall_lines.append({
                            "level_key":
                                level_key,
                            "start":
                                start,
                            "end":
                                end,
                            "source":
                                "arc_segment",
                        })

                    warnings.append({
                        "type": "curved_wall_segmented",
                        "layer": layer,
                    })

                else:
                    warnings.append({
                        "type": "unsupported_wall_entity",
                        "entity_type": etype,
                        "layer": layer,
                    })

            # ------------------------------------------------
            # DOOR
            # ------------------------------------------------

            elif semantic == "door":
                if etype == "LINE":
                    start, end = line_points(
                        entity,
                        scale,
                    )

                    door_candidates.append({
                        "level_key":
                            level_key,
                        "center":
                            midpoint(
                                start,
                                end,
                            ),
                        "width":
                            distance(
                                start,
                                end,
                            ),
                        "angle":
                            segment_angle(
                                start,
                                end,
                            ),
                        "source":
                            "line",
                    })

                elif etype == "ARC":
                    center = point2(
                        entity.dxf.center,
                        scale,
                    )
                    radius = (
                        float(
                            entity.dxf.radius
                        )
                        * scale
                    )

                    door_candidates.append({
                        "level_key":
                            level_key,
                        "center":
                            center,
                        "width":
                            radius,
                        "angle":
                            None,
                        "source":
                            "arc_approximation",
                    })

                    warnings.append({
                        "type":
                            "door_arc_approximated",
                        "layer":
                            layer,
                        "message":
                            "ARC door uses arc center as candidate anchor and radius as width; review required.",
                    })

                elif etype in {
                    "LWPOLYLINE",
                    "POLYLINE",
                }:
                    points = polyline_points(
                        entity,
                        scale,
                    )

                    if len(points) >= 2:
                        # Use longest segment as door leaf/opening width.
                        segments = [
                            (
                                distance(
                                    points[i],
                                    points[i + 1],
                                ),
                                points[i],
                                points[i + 1],
                            )
                            for i in range(
                                len(points) - 1
                            )
                        ]

                        if (
                            is_closed_polyline(
                                entity
                            )
                            and len(points) > 2
                        ):
                            segments.append(
                                (
                                    distance(
                                        points[-1],
                                        points[0],
                                    ),
                                    points[-1],
                                    points[0],
                                )
                            )

                        segments.sort(
                            key=lambda x: x[0],
                            reverse=True,
                        )

                        width, start, end = (
                            segments[0]
                        )

                        door_candidates.append({
                            "level_key":
                                level_key,
                            "center":
                                midpoint(
                                    start,
                                    end,
                                ),
                            "width":
                                width,
                            "angle":
                                segment_angle(
                                    start,
                                    end,
                                ),
                            "source":
                                "polyline_longest_segment",
                        })

                else:
                    warnings.append({
                        "type": "unsupported_door_entity",
                        "entity_type": etype,
                        "layer": layer,
                    })

            # ------------------------------------------------
            # COLUMN
            # ------------------------------------------------

            elif semantic == "column":
                if etype == "CIRCLE":
                    center = point2(
                        entity.dxf.center,
                        scale,
                    )
                    diameter = (
                        2.0
                        * float(
                            entity.dxf.radius
                        )
                        * scale
                    )

                    columns.append({
                        "key": next_column,
                        "name":
                            f"DXF Column {next_column}",
                        "level_key":
                            level_key,
                        "shape":
                            "circle",
                        "center":
                            center,
                        "diameter":
                            diameter,
                        "height":
                            float(
                                defaults[
                                    "column_height_m"
                                ]
                            ),
                    })
                    next_column += 1

                elif etype in {
                    "LWPOLYLINE",
                    "POLYLINE",
                }:
                    if not is_closed_polyline(
                        entity
                    ):
                        warnings.append({
                            "type": "open_column_polyline",
                            "layer": layer,
                        })
                        continue

                    points = polyline_points(
                        entity,
                        scale,
                    )

                    if len(points) < 3:
                        continue

                    props = (
                        oriented_rectangle_properties(
                            points
                        )
                    )

                    columns.append({
                        "key": next_column,
                        "name":
                            f"DXF Column {next_column}",
                        "level_key":
                            level_key,
                        "shape":
                            "rectangle",
                        "center":
                            props["center"],
                        "width":
                            props["width"],
                        "depth":
                            props["depth"],
                        "rotation_deg":
                            props[
                                "rotation_deg"
                            ],
                        "height":
                            float(
                                defaults[
                                    "column_height_m"
                                ]
                            ),
                    })
                    next_column += 1

                else:
                    warnings.append({
                        "type": "unsupported_column_entity",
                        "entity_type": etype,
                        "layer": layer,
                    })

            # ------------------------------------------------
            # EQUIPMENT
            # ------------------------------------------------

            elif semantic == "equipment":
                if etype not in {
                    "LWPOLYLINE",
                    "POLYLINE",
                }:
                    warnings.append({
                        "type": "unsupported_equipment_entity",
                        "entity_type": etype,
                        "layer": layer,
                    })
                    continue

                if not is_closed_polyline(
                    entity
                ):
                    warnings.append({
                        "type": "open_equipment_polyline",
                        "layer": layer,
                    })
                    continue

                points = polyline_points(
                    entity,
                    scale,
                )

                if len(points) < 3:
                    continue

                obstacles.append({
                    "key": next_obstacle,
                    "name":
                        f"DXF Equipment {next_obstacle}",
                    "type":
                        "equipment",
                    "level_key":
                        level_key,
                    "height":
                        float(
                            defaults[
                                "obstacle_height_m"
                            ]
                        ),
                    "z_offset":
                        float(
                            defaults[
                                "z_offset_m"
                            ]
                        ),
                    "polygon":
                        points,
                })
                next_obstacle += 1

            # ------------------------------------------------
            # VERTICAL CONNECTION
            # ------------------------------------------------

            elif semantic == "vertical_connection":
                if etype not in {
                    "LWPOLYLINE",
                    "POLYLINE",
                }:
                    warnings.append({
                        "type":
                            "unsupported_vertical_connection_entity",
                        "entity_type":
                            etype,
                        "layer":
                            layer,
                    })
                    continue

                if not is_closed_polyline(
                    entity
                ):
                    warnings.append({
                        "type":
                            "open_vertical_connection_polyline",
                        "layer":
                            layer,
                    })
                    continue

                points = polyline_points(
                    entity,
                    scale,
                )

                if len(points) < 3:
                    continue

                vertical_connections.append({
                    "key":
                        next_vertical,
                    "name":
                        f"DXF Stair/Ramp {next_vertical}",
                    "type":
                        "stairway",
                    "start_level":
                        level_key,
                    "end_level":
                        level_key + 1,
                    "start_z_offset":
                        0.0,
                    "end_z_offset":
                        0.0,
                    "polygon":
                        points,
                    "steps":
                        24,
                    "thickness":
                        0.20,
                    "show_balustrade":
                        True,
                })
                next_vertical += 1

    # ========================================================
    # WALL NORMALIZATION
    # ========================================================

    pair_walls, single_lines = (
        pair_double_wall_lines(
            raw_wall_lines,
            defaults,
        )
    )

    normalized_walls = []

    # First: paired double-line walls.
    for item in pair_walls:
        normalized_walls.append({
            "level_key":
                item["level_key"],
            "start":
                item["start"],
            "end":
                item["end"],
            "thickness":
                item["thickness"],
            "source":
                item["source"],
        })

    # Second: unpaired centerline walls.
    for item in single_lines:
        normalized_walls.append({
            "level_key":
                item["level_key"],
            "start":
                item["start"],
            "end":
                item["end"],
            "thickness":
                float(
                    defaults[
                        "wall_thickness_m"
                    ]
                ),
            "source":
                item["source"],
        })

    # Third: closed wall polygons -> oriented wall rectangles.
    for item in polygon_walls:
        props = (
            oriented_rectangle_properties(
                item["points"]
            )
        )

        normalized_walls.append({
            "level_key":
                item["level_key"],
            "start":
                props[
                    "centerline_start"
                ],
            "end":
                props[
                    "centerline_end"
                ],
            "thickness":
                props["thickness"],
            "source":
                "closed_wall_polygon",
        })

    # Assign deterministic wall keys.
    walls = []

    for index, item in enumerate(
        normalized_walls,
        start=1101,
    ):
        walls.append({
            "key": index,
            "name":
                f"DXF Wall {index}",
            "level_key":
                item["level_key"],
            "start":
                item["start"],
            "end":
                item["end"],
            "thickness":
                item["thickness"],
            "height":
                float(
                    defaults[
                        "wall_height_m"
                    ]
                ),
            "openings":
                [],
            "_source_mode":
                item["source"],
        })

    # ========================================================
    # DOOR -> WALL ASSOCIATION
    # ========================================================

    unassigned_doors = []

    door_distance_tol = float(
        defaults[
            "door_to_wall_tolerance_m"
        ]
    )

    angle_tol = float(
        defaults[
            "parallel_angle_tolerance_deg"
        ]
    )

    for door_index, door in enumerate(
        door_candidates,
        start=1,
    ):
        door_point = Point(
            door["center"]
        )

        candidates = []

        for wall in walls:
            if (
                wall["level_key"]
                != door["level_key"]
            ):
                continue

            wall_line = LineString(
                [
                    wall["start"],
                    wall["end"],
                ]
            )

            wall_distance = (
                wall_line.distance(
                    door_point
                )
            )

            # For ARC-derived door candidates angle is unknown.
            if door["angle"] is None:
                angle_diff = 0.0
            else:
                angle_diff = (
                    angle_difference(
                        segment_angle(
                            wall["start"],
                            wall["end"],
                        ),
                        door["angle"],
                    )
                )

            effective_tol = max(
                door_distance_tol,
                wall["thickness"]
                / 2.0
                + door_distance_tol,
            )

            if (
                wall_distance
                <= effective_tol
                and angle_diff
                <= angle_tol
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
                "door_index":
                    door_index,
                **door,
            })
            continue

        candidates.sort(
            key=lambda x: (
                x[0],
                x[1],
                x[2]["key"],
            )
        )

        wall = candidates[0][2]

        wall["openings"].append({
            "name":
                f"DXF Door D{door_index:02d}",
            "center":
                door["center"],
            "width":
                door["width"],
        })

    # ========================================================
    # LEVELS
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

    for item in vertical_connections:
        used_levels.add(
            int(item["start_level"])
        )
        used_levels.add(
            int(item["end_level"])
        )

    if not used_levels:
        used_levels.add(
            int(
                defaults.get(
                    "default_level",
                    1,
                )
            )
        )

    default_level_height = float(
        defaults.get(
            "level_height_m",
            4.0,
        )
    )

    levels = []

    for key in sorted(
        used_levels
    ):
        levels.append({
            "key":
                key,
            "name":
                (
                    "Ground Floor"
                    if key == 1
                    else f"Level {key}"
                ),
            "z":
                (key - 1)
                * default_level_height,
        })

    # Remove internal parser notes before engine handoff.
    for wall in walls:
        wall.pop(
            "_source_mode",
            None,
        )

    model = {
        "project": {
            "name":
                "DXF Imported Viswalk Model v0.2",
            "units":
                "m",
            "source":
                str(DXF_FILE),
        },

        "defaults": {
            "wall_height":
                float(
                    defaults[
                        "wall_height_m"
                    ]
                ),
            "column_height":
                float(
                    defaults[
                        "column_height_m"
                    ]
                ),
            "obstacle_height":
                float(
                    defaults[
                        "obstacle_height_m"
                    ]
                ),
            "z_offset":
                float(
                    defaults[
                        "z_offset_m"
                    ]
                ),
            "level_key":
                int(
                    defaults[
                        "default_level"
                    ]
                ),
        },

        "transform": {
            "scale":
                1.0,
            "rotation_deg":
                0.0,
            "origin":
                [0.0, 0.0],
        },

        "levels":
            levels,
        "areas":
            areas,
        "walls":
            walls,
        "columns":
            columns,
        "obstacles":
            obstacles,
        "vertical_connections":
            vertical_connections,
    }

    report = {
        "source_file":
            str(DXF_FILE),
        "scale_to_meters":
            scale,
        "scale_basis":
            scale_basis,
        "expanded_inserts":
            expanded_inserts,
        "raw_wall_lines":
            len(raw_wall_lines),
        "double_line_wall_pairs":
            len(pair_walls),
        "single_wall_lines":
            len(single_lines),
        "closed_wall_polygons":
            len(polygon_walls),
        "areas":
            len(areas),
        "walls":
            len(walls),
        "columns":
            len(columns),
        "obstacles":
            len(obstacles),
        "vertical_connections":
            len(vertical_connections),
        "doors_detected":
            len(door_candidates),
        "doors_assigned":
            len(door_candidates)
            - len(unassigned_doors),
        "doors_unassigned":
            unassigned_doors,
        "ignored_entities":
            ignored,
        "warnings":
            warnings,
        "status":
            (
                "REVIEW"
                if (
                    warnings
                    or unassigned_doors
                )
                else "PASS"
            ),
    }

    return model, report


# ============================================================
# MAIN
# ============================================================

def main():
    print(
        "Viswalk DXF Ingestion v0.2"
    )
    print("=" * 60)

    if not DXF_FILE.exists():
        raise FileNotFoundError(
            f"DXF not found: {DXF_FILE}"
        )

    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Config not found: {CONFIG_FILE}"
        )

    config = load_json(
        CONFIG_FILE
    )

    doc = ezdxf.readfile(
        DXF_FILE
    )

    model, report = ingest(
        doc,
        config,
    )

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
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

    print()
    print(
        "Scale to meters:",
        report["scale_to_meters"],
        f"({report['scale_basis']})",
    )
    print(
        "Expanded INSERTs:",
        report["expanded_inserts"],
    )
    print(
        "Raw wall lines:",
        report["raw_wall_lines"],
    )
    print(
        "Double-line wall pairs:",
        report["double_line_wall_pairs"],
    )
    print(
        "Areas:",
        report["areas"],
    )
    print(
        "Walls:",
        report["walls"],
    )
    print(
        "Columns:",
        report["columns"],
    )
    print(
        "Obstacles:",
        report["obstacles"],
    )
    print(
        "Vertical connections:",
        report["vertical_connections"],
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
            report[
                "doors_unassigned"
            ]
        ),
    )
    print(
        "Warnings:",
        len(
            report["warnings"]
        ),
    )

    print()
    print(
        "Ingestion status:",
        report["status"],
    )

    print()
    print(
        "Generated geometry JSON:"
    )
    print(
        OUTPUT_JSON
    )

    print()
    print(
        "Report:"
    )
    print(
        REPORT_FILE
    )


if __name__ == "__main__":
    main()
