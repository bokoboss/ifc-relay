import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
CANDIDATE_FILE = PROJECT_DIR / "candidate_model_v02.json"
STATE_FILE = PROJECT_DIR / "review_workspace_state.json"
OUTPUT_CANDIDATE_FILE = PROJECT_DIR / "candidate_model_workspace_reviewed.json"
OUTPUT_GEOMETRY_FILE = PROJECT_DIR / "geometry_from_pdf_workspace.json"
REPORT_FILE = PROJECT_DIR / "output" / "review_workspace_handoff_report.json"

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
                openings = []
                for i, op in enumerate(c["properties"].get("openings", []), start=1):
                    openings.append(
                        {
                            "name": op.get("name", f"Workspace Door D{i:02d}"),
                            "center": [float(op["center"][0]), float(op["center"][1])],
                            "width": float(op["width"]),
                        }
                    )

                walls.append(
                    {
                        "key": wall_key,
                        "name": f"Workspace Wall {wall_key}",
                        "level_key": int(c["properties"]["level_key"]),
                        "start": [float(c["geometry"]["start"][0]), float(c["geometry"]["start"][1])],
                        "end": [float(c["geometry"]["end"][0]), float(c["geometry"]["end"][1])],
                        "thickness": float(c["properties"]["thickness"]),
                        "height": float(c["properties"].get("height", 3.0)),
                        "openings": openings,
                    }
                )
                wall_key += 1

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
            "name": "PDF Review Workspace Viswalk Model v0.2",
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
        "source_workspace_state": str(STATE_FILE),
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
        "status": "REVIEW" if provisional else "PASS",
    }

    return geometry, report


def main():
    if not CANDIDATE_FILE.exists():
        raise FileNotFoundError(CANDIDATE_FILE)
    if not STATE_FILE.exists():
        raise FileNotFoundError(
            "review_workspace_state.json not found. Export it from review_workspace_v02.html."
        )

    base_model = load_json(CANDIDATE_FILE)
    state = load_json(STATE_FILE)

    if state.get("schema_version") != "0.2":
        raise ValueError("Unsupported workspace schema; expected 0.2")

    decisions = state.get("decisions", {})
    invalid = {k: v for k, v in decisions.items() if v not in {"approve", "reject"}}
    if invalid:
        raise ValueError(f"Unsupported review decisions: {invalid}")

    model = merged_model(base_model, state)
    geometry, report = build_geometry(model, decisions)
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

    print("Review Workspace Handoff v0.2")
    print("=" * 60)
    print("Manual decisions:", report["manual_decision_count"])
    for key, value in report["geometry_counts"].items():
        print(f"{key:<22}: {value}")
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
