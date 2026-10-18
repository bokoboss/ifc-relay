import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
CANDIDATE_FILE = PROJECT_DIR / "candidate_model_v02.json"
STATE_FILE_V03 = PROJECT_DIR / "review_workspace_state_v03.json"
STATE_FILE_V02 = PROJECT_DIR / "review_workspace_state.json"
OUTPUT_CANDIDATE_FILE = PROJECT_DIR / "candidate_model_workspace_reviewed.json"
OUTPUT_GEOMETRY_FILE = PROJECT_DIR / "geometry_from_pdf_workspace_v03.json"
REPORT_FILE = PROJECT_DIR / "output" / "review_workspace_v03_handoff_report.json"

PROVISIONAL_TYPES = {"stairway", "column"}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def merged_model(base_model, state):
    model = json.loads(json.dumps(base_model))
    overrides = state.get("candidates", {})

    for page in model["pages"]:
        new_candidates = []
        for c in page["candidates"]:
            replacement = overrides.get(c["id"])
            if replacement is not None:
                new_candidates.append(json.loads(json.dumps(replacement)))
            else:
                new_candidates.append(c)
        page["candidates"] = new_candidates

    return model


def manual_state(candidate_id, decisions):
    decision = decisions.get(candidate_id)
    if decision == "approve":
        return "approved"
    if decision == "reject":
        return "rejected"
    return "unchanged"


def include_candidate(candidate, state):
    if state == "approved":
        return True
    if state == "rejected":
        return False
    if candidate["status"] == "auto_accept":
        return True
    return (
        candidate["status"] == "review_recommended"
        and candidate["type"] in PROVISIONAL_TYPES
    )


def validate_polygon(poly, label):
    if not isinstance(poly, list) or len(poly) < 3:
        raise ValueError(f"{label}: polygon must contain at least 3 points")
    for p in poly:
        if not isinstance(p, list) or len(p) != 2:
            raise ValueError(f"{label}: invalid point {p}")



def split_wall_by_openings(start, end, openings, min_segment=1e-6):
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    dx = ex - sx
    dy = ey - sy
    length = (dx * dx + dy * dy) ** 0.5

    if length <= min_segment:
        raise ValueError("Wall length is zero.")

    ux = dx / length
    uy = dy / length

    intervals = []
    normalized = []

    for index, op in enumerate(openings, start=1):
        center = op.get("center")
        width = float(op.get("width", 0.0))

        if not center or len(center) != 2 or width <= 0:
            continue

        cx = float(center[0])
        cy = float(center[1])

        # Project door center onto the logical wall centerline.
        t = (cx - sx) * ux + (cy - sy) * uy
        t_clamped = max(0.0, min(length, t))
        projected = [
            sx + ux * t_clamped,
            sy + uy * t_clamped,
        ]

        a = max(0.0, t_clamped - width / 2.0)
        b = min(length, t_clamped + width / 2.0)

        if b - a <= min_segment:
            continue

        intervals.append([a, b])
        normalized.append(
            {
                "name": op.get("name", f"Door {index}"),
                "center": projected,
                "width": b - a,
                "requested_width": width,
                "distance_along_wall": t_clamped,
            }
        )

    intervals.sort(key=lambda item: item[0])

    merged = []
    for a, b in intervals:
        if not merged or a > merged[-1][1] + min_segment:
            merged.append([a, b])
        else:
            merged[-1][1] = max(merged[-1][1], b)

    segments = []
    cursor = 0.0

    for a, b in merged:
        if a - cursor > min_segment:
            segments.append(
                (
                    [sx + ux * cursor, sy + uy * cursor],
                    [sx + ux * a, sy + uy * a],
                )
            )
        cursor = max(cursor, b)

    if length - cursor > min_segment:
        segments.append(
            (
                [sx + ux * cursor, sy + uy * cursor],
                [ex, ey],
            )
        )

    return segments, normalized, merged


def build_geometry(model, decisions):
    levels = {}
    areas = []
    walls = []
    columns = []
    obstacles = []
    vertical_connections = []

    included = []
    excluded = []
    provisional = []
    wall_segmentation = []

    area_key = 1001
    wall_key = 1101
    column_key = 1301
    obstacle_key = 1401
    vertical_key = 2001

    for page in model["pages"]:
        for c in page["candidates"]:
            state = manual_state(c["id"], decisions)
            c["manual_decision"] = state
            ctype = c["type"]

            if not include_candidate(c, state):
                if ctype not in {"scale", "level"}:
                    excluded.append(
                        {
                            "id": c["id"],
                            "type": ctype,
                            "manual_decision": state,
                            "status": c["status"],
                            "confidence": c["confidence"],
                        }
                    )
                continue

            included.append(c["id"])

            if state == "unchanged" and c["status"] == "review_recommended":
                provisional.append(c["id"])

            if ctype == "level":
                lk = int(c["properties"]["level_key"])
                levels[lk] = {
                    "key": lk,
                    "name": "Ground Floor" if lk == 1 else f"Level {lk}",
                    "z": float(c["properties"]["z"]),
                }

            elif ctype == "area":
                validate_polygon(c["geometry"]["polygon"], c["id"])
                areas.append(
                    {
                        "key": area_key,
                        "name": f"Workspace Area {area_key}",
                        "level_key": int(c["properties"]["level_key"]),
                        "polygon": c["geometry"]["polygon"],
                    }
                )
                area_key += 1

            elif ctype == "wall":
                logical_start = [
                    float(c["geometry"]["start"][0]),
                    float(c["geometry"]["start"][1]),
                ]
                logical_end = [
                    float(c["geometry"]["end"][0]),
                    float(c["geometry"]["end"][1]),
                ]
                source_openings = c["properties"].get("openings", [])
                physical_segments, normalized_openings, gap_intervals = split_wall_by_openings(
                    logical_start,
                    logical_end,
                    source_openings,
                )

                if not physical_segments:
                    excluded.append(
                        {
                            "id": c["id"],
                            "type": "wall",
                            "manual_decision": state,
                            "status": c["status"],
                            "confidence": c["confidence"],
                            "reason": "openings consume entire wall",
                        }
                    )
                    continue

                segment_count = len(physical_segments)
                for segment_index, (segment_start, segment_end) in enumerate(
                    physical_segments,
                    start=1,
                ):
                    walls.append(
                        {
                            "key": wall_key,
                            "name": (
                                f"Workspace Wall {c['id']} "
                                f"[segment {segment_index}/{segment_count}]"
                            ),
                            "level_key": int(c["properties"]["level_key"]),
                            "start": segment_start,
                            "end": segment_end,
                            "thickness": float(c["properties"]["thickness"]),
                            "height": float(c["properties"].get("height", 3.0)),
                            "openings": [],
                            "source_logical_wall_id": c["id"],
                        }
                    )
                    wall_key += 1

                wall_segmentation.append(
                    {
                        "logical_wall_id": c["id"],
                        "logical_start": logical_start,
                        "logical_end": logical_end,
                        "opening_count": len(normalized_openings),
                        "openings": normalized_openings,
                        "gap_intervals_m": gap_intervals,
                        "physical_segment_count": segment_count,
                    }
                )

            elif ctype == "column":
                p = c["properties"]
                item = {
                    "key": column_key,
                    "name": f"Workspace Column {column_key}",
                    "level_key": int(p["level_key"]),
                    "shape": p["shape"],
                    "center": [float(c["geometry"]["center"][0]), float(c["geometry"]["center"][1])],
                    "height": float(p.get("height", 3.0)),
                }

                if p["shape"] == "circle":
                    item["diameter"] = float(p["diameter"])
                else:
                    item.update(
                        {
                            "width": float(p["width"]),
                            "depth": float(p["depth"]),
                            "rotation_deg": float(p.get("rotation_deg", 0.0)),
                        }
                    )

                columns.append(item)
                column_key += 1

            elif ctype == "equipment":
                validate_polygon(c["geometry"]["polygon"], c["id"])
                obstacles.append(
                    {
                        "key": obstacle_key,
                        "name": f"Workspace Equipment {obstacle_key}",
                        "type": "equipment",
                        "level_key": int(c["properties"]["level_key"]),
                        "height": float(c["properties"].get("height", 1.2)),
                        "z_offset": 0.0,
                        "polygon": c["geometry"]["polygon"],
                    }
                )
                obstacle_key += 1

            elif ctype == "stairway":
                validate_polygon(c["geometry"]["polygon"], c["id"])
                p = c["properties"]
                vertical_connections.append(
                    {
                        "key": vertical_key,
                        "name": f"Workspace Stair {vertical_key}",
                        "type": "stairway",
                        "start_level": int(p["start_level"]),
                        "end_level": int(p["end_level"]),
                        "start_z_offset": 0.0,
                        "end_z_offset": 0.0,
                        "polygon": c["geometry"]["polygon"],
                        "steps": int(p.get("steps", 24)),
                        "thickness": float(p.get("thickness", 0.2)),
                        "show_balustrade": bool(p.get("show_balustrade", True)),
                    }
                )
                vertical_key += 1

            elif ctype == "unknown_rectangle":
                raise ValueError(
                    f"{c['id']} was approved while still unknown. "
                    "Convert it to Equipment or Column in Review Workspace first."
                )

    for page in model["pages"]:
        lk = int(page["level_key"])
        levels.setdefault(
            lk,
            {
                "key": lk,
                "name": "Ground Floor" if lk == 1 else f"Level {lk}",
                "z": (lk - 1) * 4.0,
            },
        )

    geometry = {
        "project": {
            "name": "PDF Review Workspace Viswalk Model v0.3",
            "units": "m",
            "source": model["source_file"],
        },
        "defaults": {
            "wall_height": 3.0,
            "column_height": 3.0,
            "obstacle_height": 1.2,
            "z_offset": 0.0,
            "level_key": 1,
        },
        "transform": {
            "scale": 1.0,
            "rotation_deg": 0.0,
            "origin": [0.0, 0.0],
        },
        "levels": [levels[k] for k in sorted(levels)],
        "areas": areas,
        "walls": walls,
        "columns": columns,
        "obstacles": obstacles,
        "vertical_connections": vertical_connections,
    }

    report = {
        "source_candidate_file": str(CANDIDATE_FILE),
        "source_workspace_state": None,
        "manual_decision_count": len(decisions),
        "edited_candidate_count": sum(
            1 for page in model["pages"] for c in page["candidates"] if c["id"] in decisions
        ),
        "included_candidate_ids": included,
        "provisional_candidate_ids": provisional,
        "excluded": excluded,
        "geometry_counts": {
            "levels": len(geometry["levels"]),
            "areas": len(areas),
            "walls": len(walls),
            "columns": len(columns),
            "obstacles": len(obstacles),
            "vertical_connections": len(vertical_connections),
        },
        "wall_segmentation": wall_segmentation,
        "logical_wall_count": len(wall_segmentation),
        "physical_wall_segment_count": len(walls),
        "wall_opening_count": sum(item["opening_count"] for item in wall_segmentation),
        "status": "REVIEW" if provisional else "PASS",
    }

    return geometry, report


def main():
    if not CANDIDATE_FILE.exists():
        raise FileNotFoundError(CANDIDATE_FILE)

    state_file = STATE_FILE_V03 if STATE_FILE_V03.exists() else STATE_FILE_V02
    if not state_file.exists():
        raise FileNotFoundError(
            "No workspace state found. Export review_workspace_state_v03.json "
            "from review_workspace_v03.html and place it in the project folder."
        )

    base_model = load_json(CANDIDATE_FILE)
    state = load_json(state_file)

    if state.get("schema_version") not in {"0.2", "0.3"}:
        raise ValueError("Unsupported workspace schema; expected 0.2 or 0.3")

    decisions = state.get("decisions", {})
    invalid = {k: v for k, v in decisions.items() if v not in {"approve", "reject"}}
    if invalid:
        raise ValueError(f"Unsupported review decisions: {invalid}")

    model = merged_model(base_model, state)
    geometry, report = build_geometry(model, decisions)
    report["source_workspace_state"] = str(state_file)
    report["edited_candidate_count"] = len(state.get("candidates", {}))

    OUTPUT_CANDIDATE_FILE.write_text(
        json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    OUTPUT_GEOMETRY_FILE.write_text(
        json.dumps(geometry, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("Review Workspace Handoff v0.3")
    print("=" * 60)
    print("Manual decisions:", report["manual_decision_count"])
    for key, value in report["geometry_counts"].items():
        print(f"{key:<22}: {value}")
    print("Logical walls          :", report["logical_wall_count"])
    print("Physical wall segments :", report["physical_wall_segment_count"])
    print("Wall openings          :", report["wall_opening_count"])
    print("Provisional candidates:", len(report["provisional_candidate_ids"]))
    print("Excluded candidates:", len(report["excluded"]))
    print("Status:", report["status"])
    print()
    print("Geometry for Vissim:")
    print(OUTPUT_GEOMETRY_FILE)
    print()
    print("Report:")
    print(REPORT_FILE)


if __name__ == "__main__":
    main()
