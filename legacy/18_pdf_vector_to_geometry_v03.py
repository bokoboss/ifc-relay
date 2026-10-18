import json
import math
import re
from pathlib import Path

import fitz
from shapely.geometry import LineString, Point, Polygon


PROJECT_DIR = Path(__file__).resolve().parent
PDF_FILE = PROJECT_DIR / "sample_floorplan_vector.pdf"
CONFIG_FILE = PROJECT_DIR / "pdf_vector_mapping.json"
OUTPUT_JSON = PROJECT_DIR / "geometry_from_pdf_vector.json"
REPORT_FILE = PROJECT_DIR / "output" / "pdf_vector_ingestion_report.json"

SCALE_PATTERN = re.compile(r"SCALE\s*1\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
LEVEL_PATTERN = re.compile(r"LEVEL\s+(\d+)", re.IGNORECASE)


# ============================================================
# HELPERS
# ============================================================

def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def color_close(actual, expected, tolerance):
    if actual is None or expected is None:
        return actual is None and expected is None
    if len(actual) < 3 or len(expected) < 3:
        return False
    return all(
        abs(float(actual[i]) - float(expected[i])) <= tolerance
        for i in range(3)
    )


def classify_drawing(drawing, config):
    tol = float(config["defaults"]["style_color_tolerance"])
    stroke = drawing.get("color")
    fill = drawing.get("fill")

    styles = config["styles"]

    # Prefer fill-based semantics first because filled shapes may also have stroke.
    for semantic in (
        "column",
        "equipment",
        "vertical_connection",
    ):
        expected_fill = styles[semantic].get("fill")
        if expected_fill is not None and color_close(fill, expected_fill, tol):
            return semantic

    for semantic in ("area", "door", "wall"):
        expected_stroke = styles[semantic].get("stroke")
        if expected_stroke is None:
            continue
        if not color_close(stroke, expected_stroke, tol):
            continue

        expected_fill = styles[semantic].get("fill", "ANY")
        if expected_fill == "ANY":
            return semantic
        if expected_fill is None and fill is not None:
            continue
        if expected_fill is not None and not color_close(fill, expected_fill, tol):
            continue
        return semantic

    return None


def pt_to_m_factor(scale_denominator):
    # 1 pt = 1/72 inch = 25.4/72 mm on paper.
    # Real distance = paper distance * scale denominator.
    return (25.4 / 72.0) * float(scale_denominator) / 1000.0


def pdf_point_to_world(point, page_height_pt, factor):
    # PyMuPDF coordinates are top-left origin.
    # Convert to a conventional bottom-left Cartesian orientation.
    return [
        float(point.x) * factor,
        (float(page_height_pt) - float(point.y)) * factor,
    ]


def rect_corners_world(rect, page_height_pt, factor):
    p1 = pdf_point_to_world(rect.tl, page_height_pt, factor)
    p2 = pdf_point_to_world(rect.tr, page_height_pt, factor)
    p3 = pdf_point_to_world(rect.br, page_height_pt, factor)
    p4 = pdf_point_to_world(rect.bl, page_height_pt, factor)
    return [p1, p2, p3, p4]


def distance(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def midpoint(a, b):
    return [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]


def segment_angle(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0


def angle_difference(a, b):
    diff = abs(a - b) % 180.0
    return min(diff, 180.0 - diff)


def dedupe_points(points, tol=1e-8):
    result = []
    for point in points:
        if not result or distance(result[-1], point) > tol:
            result.append(point)
    if len(result) >= 2 and distance(result[0], result[-1]) <= tol:
        result.pop()
    return result


def drawing_line_segments(drawing, page_height_pt, factor):
    segments = []
    for item in drawing.get("items", []):
        code = item[0]
        if code == "l":
            a = pdf_point_to_world(item[1], page_height_pt, factor)
            b = pdf_point_to_world(item[2], page_height_pt, factor)
            segments.append((a, b))
        elif code == "re":
            rect = item[1]
            pts = rect_corners_world(rect, page_height_pt, factor)
            for i in range(4):
                segments.append((pts[i], pts[(i + 1) % 4]))
    return segments


def drawing_polygon_points(drawing, page_height_pt, factor):
    points = []

    for item in drawing.get("items", []):
        code = item[0]

        if code == "re":
            return rect_corners_world(item[1], page_height_pt, factor)

        if code == "l":
            a = pdf_point_to_world(item[1], page_height_pt, factor)
            b = pdf_point_to_world(item[2], page_height_pt, factor)
            if not points:
                points.append(a)
            points.append(b)

        elif code == "c":
            # For closed curved shapes (e.g. circles), polygon extraction is
            # intentionally not attempted here. Caller can use the bbox.
            continue

    return dedupe_points(points)


def oriented_rectangle_properties(points):
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    rect = polygon.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:-1]

    edges = []
    for i in range(4):
        a = coords[i]
        b = coords[(i + 1) % 4]
        edges.append((distance(a, b), a, b))

    edges.sort(key=lambda x: x[0], reverse=True)
    long_length, long_a, long_b = edges[0]
    short_length = edges[-1][0]

    center = [float(rect.centroid.x), float(rect.centroid.y)]
    angle = segment_angle(long_a, long_b)

    return {
        "center": center,
        "width": long_length,
        "depth": short_length,
        "rotation_deg": angle,
    }


def translate_point(point, origin):
    return [point[0] - origin[0], point[1] - origin[1]]


def translate_points(points, origin):
    return [translate_point(p, origin) for p in points]


# ============================================================
# PAGE INGESTION
# ============================================================

def ingest_page(page, page_index, config):
    text = page.get_text("text")

    level_match = LEVEL_PATTERN.search(text)
    if not level_match:
        raise ValueError(f"Page {page_index + 1}: LEVEL n text not found.")
    level_key = int(level_match.group(1))

    override = config.get("scale_denominator_override")
    if override is not None:
        scale_denominator = float(override)
    else:
        scale_match = SCALE_PATTERN.search(text)
        if not scale_match:
            raise ValueError(
                f"Page {page_index + 1}: SCALE 1:n text not found."
            )
        scale_denominator = float(scale_match.group(1))

    factor = pt_to_m_factor(scale_denominator)
    drawings = page.get_drawings()

    classified = []
    ignored = []

    for drawing_index, drawing in enumerate(drawings, start=1):
        semantic = classify_drawing(drawing, config)
        if semantic is None:
            ignored.append({
                "drawing_index": drawing_index,
                "stroke": drawing.get("color"),
                "fill": drawing.get("fill"),
            })
            continue
        classified.append((semantic, drawing))

    # Find AREA first and use its lower-left as local origin.
    area_drawings = [d for s, d in classified if s == "area"]
    if not area_drawings:
        raise ValueError(f"Page {page_index + 1}: no AREA vector found.")

    area_rect = area_drawings[0]["rect"]
    area_points_abs = rect_corners_world(
        area_rect,
        page.rect.height,
        factor,
    )
    origin = [
        min(p[0] for p in area_points_abs),
        min(p[1] for p in area_points_abs),
    ]

    page_model = {
        "level_key": level_key,
        "scale_denominator": scale_denominator,
        "pt_to_m": factor,
        "origin_abs_m": origin,
        "areas": [],
        "walls": [],
        "doors": [],
        "columns": [],
        "obstacles": [],
        "vertical_connections": [],
        "ignored_drawings": ignored,
    }

    for semantic, drawing in classified:
        if semantic == "area":
            points = drawing_polygon_points(
                drawing,
                page.rect.height,
                factor,
            )
            if not points:
                points = rect_corners_world(
                    drawing["rect"],
                    page.rect.height,
                    factor,
                )
            page_model["areas"].append(
                translate_points(points, origin)
            )

        elif semantic == "wall":
            segments = drawing_line_segments(
                drawing,
                page.rect.height,
                factor,
            )
            for start, end in segments:
                start = translate_point(start, origin)
                end = translate_point(end, origin)
                if distance(start, end) > 1e-6:
                    page_model["walls"].append({
                        "start": start,
                        "end": end,
                    })

        elif semantic == "door":
            segments = drawing_line_segments(
                drawing,
                page.rect.height,
                factor,
            )
            if not segments:
                continue
            start, end = max(
                segments,
                key=lambda s: distance(s[0], s[1]),
            )
            start = translate_point(start, origin)
            end = translate_point(end, origin)
            page_model["doors"].append({
                "center": midpoint(start, end),
                "width": distance(start, end),
                "angle": segment_angle(start, end),
            })

        elif semantic == "column":
            item_codes = [item[0] for item in drawing.get("items", [])]
            rect = drawing["rect"]
            bbox_points = rect_corners_world(
                rect,
                page.rect.height,
                factor,
            )
            bbox_points = translate_points(bbox_points, origin)

            has_curve = "c" in item_codes
            bbox_width = max(p[0] for p in bbox_points) - min(p[0] for p in bbox_points)
            bbox_height = max(p[1] for p in bbox_points) - min(p[1] for p in bbox_points)

            if has_curve and abs(bbox_width - bbox_height) <= 0.05:
                center = [
                    (min(p[0] for p in bbox_points) + max(p[0] for p in bbox_points)) / 2.0,
                    (min(p[1] for p in bbox_points) + max(p[1] for p in bbox_points)) / 2.0,
                ]
                page_model["columns"].append({
                    "shape": "circle",
                    "center": center,
                    "diameter": (bbox_width + bbox_height) / 2.0,
                })
            else:
                points = drawing_polygon_points(
                    drawing,
                    page.rect.height,
                    factor,
                )
                points = translate_points(points, origin)
                if len(points) >= 3:
                    props = oriented_rectangle_properties(points)
                else:
                    props = oriented_rectangle_properties(bbox_points)
                page_model["columns"].append({
                    "shape": "rectangle",
                    **props,
                })

        elif semantic == "equipment":
            points = drawing_polygon_points(
                drawing,
                page.rect.height,
                factor,
            )
            if not points:
                points = rect_corners_world(
                    drawing["rect"],
                    page.rect.height,
                    factor,
                )
            page_model["obstacles"].append(
                translate_points(points, origin)
            )

        elif semantic == "vertical_connection":
            points = drawing_polygon_points(
                drawing,
                page.rect.height,
                factor,
            )
            if not points:
                points = rect_corners_world(
                    drawing["rect"],
                    page.rect.height,
                    factor,
                )
            page_model["vertical_connections"].append(
                translate_points(points, origin)
            )

    return page_model


# ============================================================
# WHOLE DOCUMENT
# ============================================================

def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(f"PDF not found: {PDF_FILE}")
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config not found: {CONFIG_FILE}")

    config = load_json(CONFIG_FILE)
    defaults = config["defaults"]

    doc = fitz.open(PDF_FILE)

    page_models = [
        ingest_page(page, i, config)
        for i, page in enumerate(doc)
    ]

    areas = []
    walls = []
    doors = []
    columns = []
    obstacles = []
    vertical_connections = []
    levels_seen = set()

    next_area = 1001
    next_wall = 1101
    next_column = 1301
    next_obstacle = 1401
    next_vertical = 2001

    ignored_count = 0

    for page_model in page_models:
        level_key = page_model["level_key"]
        levels_seen.add(level_key)
        ignored_count += len(page_model["ignored_drawings"])

        for polygon in page_model["areas"]:
            areas.append({
                "key": next_area,
                "name": f"PDF Area {next_area}",
                "level_key": level_key,
                "polygon": polygon,
            })
            next_area += 1

        for item in page_model["walls"]:
            walls.append({
                "key": next_wall,
                "name": f"PDF Wall {next_wall}",
                "level_key": level_key,
                "start": item["start"],
                "end": item["end"],
                "thickness": float(defaults["wall_thickness_m"]),
                "height": float(defaults["wall_height_m"]),
                "openings": [],
            })
            next_wall += 1

        for item in page_model["doors"]:
            doors.append({
                "level_key": level_key,
                **item,
            })

        for item in page_model["columns"]:
            record = {
                "key": next_column,
                "name": f"PDF Column {next_column}",
                "level_key": level_key,
                "shape": item["shape"],
                "center": item["center"],
                "height": float(defaults["column_height_m"]),
            }
            if item["shape"] == "circle":
                record["diameter"] = item["diameter"]
            else:
                record["width"] = item["width"]
                record["depth"] = item["depth"]
                record["rotation_deg"] = item["rotation_deg"]
            columns.append(record)
            next_column += 1

        for polygon in page_model["obstacles"]:
            obstacles.append({
                "key": next_obstacle,
                "name": f"PDF Equipment {next_obstacle}",
                "type": "equipment",
                "level_key": level_key,
                "height": float(defaults["obstacle_height_m"]),
                "z_offset": float(defaults["z_offset_m"]),
                "polygon": polygon,
            })
            next_obstacle += 1

        for polygon in page_model["vertical_connections"]:
            vertical_connections.append({
                "key": next_vertical,
                "name": f"PDF Stair {next_vertical}",
                "type": "stairway",
                "start_level": level_key,
                "end_level": level_key + 1,
                "start_z_offset": 0.0,
                "end_z_offset": 0.0,
                "polygon": polygon,
                "steps": 24,
                "thickness": 0.20,
                "show_balustrade": True,
            })
            levels_seen.add(level_key + 1)
            next_vertical += 1

    # ========================================================
    # ASSOCIATE DOORS TO WALLS
    # ========================================================

    unassigned_doors = []
    distance_tol = float(defaults["door_to_wall_tolerance_m"])
    angle_tol = float(defaults["parallel_angle_tolerance_deg"])

    for door_index, door in enumerate(doors, start=1):
        p = Point(door["center"])
        candidates = []

        for wall in walls:
            if wall["level_key"] != door["level_key"]:
                continue

            line = LineString([wall["start"], wall["end"]])
            d = line.distance(p)
            ad = angle_difference(
                segment_angle(wall["start"], wall["end"]),
                door["angle"],
            )

            if d <= distance_tol and ad <= angle_tol:
                candidates.append((d, ad, wall))

        if not candidates:
            unassigned_doors.append({
                "door_index": door_index,
                **door,
            })
            continue

        candidates.sort(key=lambda x: (x[0], x[1], x[2]["key"]))
        wall = candidates[0][2]
        wall["openings"].append({
            "name": f"PDF Door D{door_index:02d}",
            "center": door["center"],
            "width": door["width"],
        })

    level_height = float(defaults["level_height_m"])
    levels = [
        {
            "key": key,
            "name": "Ground Floor" if key == 1 else f"Level {key}",
            "z": (key - 1) * level_height,
        }
        for key in sorted(levels_seen)
    ]

    model = {
        "project": {
            "name": "PDF Vector Imported Viswalk Model",
            "units": "m",
            "source": str(PDF_FILE),
        },
        "defaults": {
            "wall_height": float(defaults["wall_height_m"]),
            "column_height": float(defaults["column_height_m"]),
            "obstacle_height": float(defaults["obstacle_height_m"]),
            "z_offset": float(defaults["z_offset_m"]),
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
        "vertical_connections": vertical_connections,
    }

    report = {
        "source_file": str(PDF_FILE),
        "pages": len(page_models),
        "levels": len(levels),
        "areas": len(areas),
        "walls": len(walls),
        "columns": len(columns),
        "obstacles": len(obstacles),
        "vertical_connections": len(vertical_connections),
        "doors_detected": len(doors),
        "doors_assigned": len(doors) - len(unassigned_doors),
        "doors_unassigned": unassigned_doors,
        "ignored_drawings": ignored_count,
        "page_details": [
            {
                "level_key": item["level_key"],
                "scale_denominator": item["scale_denominator"],
                "pt_to_m": item["pt_to_m"],
                "ignored_drawings": len(item["ignored_drawings"]),
            }
            for item in page_models
        ],
        "status": "PASS" if not unassigned_doors else "REVIEW",
    }

    OUTPUT_JSON.write_text(
        json.dumps(model, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Viswalk PDF Vector Ingestion v0.1")
    print("=" * 60)
    print("Pages:", report["pages"])
    print("Levels:", report["levels"])
    print("Areas:", report["areas"])
    print("Walls:", report["walls"])
    print("Columns:", report["columns"])
    print("Obstacles:", report["obstacles"])
    print("Vertical connections:", report["vertical_connections"])
    print("Doors detected:", report["doors_detected"])
    print("Doors assigned:", report["doors_assigned"])
    print("Doors unassigned:", len(report["doors_unassigned"]))
    print("Ignored drawings:", report["ignored_drawings"])
    print("Status:", report["status"])
    print()
    print("Generated JSON:")
    print(OUTPUT_JSON)
    print("Report:")
    print(REPORT_FILE)


if __name__ == "__main__":
    main()
