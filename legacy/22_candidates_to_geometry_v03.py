import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CANDIDATE_FILE = PROJECT_DIR / "candidate_model_v02.json"
OUTPUT_FILE = PROJECT_DIR / "geometry_from_pdf_interpreted.json"
REPORT_FILE = PROJECT_DIR / "output" / "candidate_handoff_report.json"

# Conservative handoff policy:
# - auto_accept: include
# - review_recommended: include provisionally for supported structural types
# - review_required: do not send to Vissim
PROVISIONAL_TYPES = {"stairway", "column"}


def main():
    model = json.loads(CANDIDATE_FILE.read_text(encoding="utf-8"))

    levels = {}
    areas = []
    walls = []
    columns = []
    obstacles = []
    vertical_connections = []
    excluded = []
    provisional = []

    area_key = 1001
    wall_key = 1101
    column_key = 1301
    obstacle_key = 1401
    vertical_key = 2001

    for page in model["pages"]:
        for c in page["candidates"]:
            ctype = c["type"]
            status = c["status"]

            include = status == "auto_accept" or (
                status == "review_recommended" and ctype in PROVISIONAL_TYPES
            )

            if not include:
                if ctype not in {"scale", "level"}:
                    excluded.append({
                        "id": c["id"],
                        "type": ctype,
                        "status": status,
                        "confidence": c["confidence"],
                    })
                continue

            if status == "review_recommended":
                provisional.append(c["id"])

            if ctype == "level":
                level_key = int(c["properties"]["level_key"])
                levels[level_key] = {
                    "key": level_key,
                    "name": "Ground Floor" if level_key == 1 else f"Level {level_key}",
                    "z": float(c["properties"]["z"]),
                }

            elif ctype == "area":
                areas.append({
                    "key": area_key,
                    "name": f"PDF Interpreted Area {area_key}",
                    "level_key": int(c["properties"]["level_key"]),
                    "polygon": c["geometry"]["polygon"],
                })
                area_key += 1

            elif ctype == "wall":
                openings = []
                for op_idx, op in enumerate(c["properties"].get("openings", []), start=1):
                    openings.append({
                        "name": f"Detected Door D{op_idx:02d}",
                        "center": op["center"],
                        "width": op["width"],
                    })

                walls.append({
                    "key": wall_key,
                    "name": f"PDF Interpreted Wall {wall_key}",
                    "level_key": int(c["properties"]["level_key"]),
                    "start": c["geometry"]["start"],
                    "end": c["geometry"]["end"],
                    "thickness": c["properties"]["thickness"],
                    "height": c["properties"].get("height", 3.0),
                    "openings": openings,
                })
                wall_key += 1

            elif ctype == "column":
                props = c["properties"]
                item = {
                    "key": column_key,
                    "name": f"PDF Interpreted Column {column_key}",
                    "level_key": int(props["level_key"]),
                    "shape": props["shape"],
                    "center": c["geometry"]["center"],
                    "height": props.get("height", 3.0),
                }
                if props["shape"] == "circle":
                    item["diameter"] = props["diameter"]
                else:
                    item["width"] = props["width"]
                    item["depth"] = props["depth"]
                    item["rotation_deg"] = props.get("rotation_deg", 0.0)
                columns.append(item)
                column_key += 1

            elif ctype == "equipment":
                obstacles.append({
                    "key": obstacle_key,
                    "name": f"PDF Interpreted Equipment {obstacle_key}",
                    "type": "equipment",
                    "level_key": int(c["properties"]["level_key"]),
                    "height": c["properties"].get("height", 1.2),
                    "z_offset": 0.0,
                    "polygon": c["geometry"]["polygon"],
                })
                obstacle_key += 1

            elif ctype == "stairway":
                props = c["properties"]
                vertical_connections.append({
                    "key": vertical_key,
                    "name": f"PDF Interpreted Stair {vertical_key}",
                    "type": "stairway",
                    "start_level": int(props["start_level"]),
                    "end_level": int(props["end_level"]),
                    "start_z_offset": 0.0,
                    "end_z_offset": 0.0,
                    "polygon": c["geometry"]["polygon"],
                    "steps": int(props.get("steps", 24)),
                    "thickness": float(props.get("thickness", 0.20)),
                    "show_balustrade": bool(props.get("show_balustrade", True)),
                })
                vertical_key += 1

    # Ensure levels exist even if a level candidate were accidentally filtered.
    for page in model["pages"]:
        level_key = int(page["level_key"])
        levels.setdefault(level_key, {
            "key": level_key,
            "name": "Ground Floor" if level_key == 1 else f"Level {level_key}",
            "z": (level_key - 1) * 4.0,
        })

    geometry = {
        "project": {
            "name": "PDF Interpreted Viswalk Model v0.2",
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
        "included": {
            "levels": len(geometry["levels"]),
            "areas": len(areas),
            "walls": len(walls),
            "columns": len(columns),
            "obstacles": len(obstacles),
            "vertical_connections": len(vertical_connections),
        },
        "provisional_candidates": provisional,
        "excluded_candidates": excluded,
        "status": "REVIEW" if provisional or excluded else "PASS",
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(geometry, indent=2, ensure_ascii=False), encoding="utf-8")
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Candidate -> Geometry v0.3 Handoff")
    print("=" * 60)
    for k, v in report["included"].items():
        print(f"{k:<22}: {v}")
    print("Provisional candidates :", len(provisional))
    print("Excluded candidates    :", len(excluded))
    print("Status                 :", report["status"])
    print()
    print("Geometry JSON:", OUTPUT_FILE)
    print("Report       :", REPORT_FILE)


if __name__ == "__main__":
    main()
