import json
import math
import re
from pathlib import Path

import fitz
from shapely.geometry import LineString, Point


PROJECT_DIR = Path(__file__).resolve().parent
PDF_FILE = PROJECT_DIR / "sample_floorplan_unstyled.pdf"
CANDIDATE_FILE = PROJECT_DIR / "candidate_model_v02.json"
REVIEW_FILE = PROJECT_DIR / "review_queue_v02.json"
REPORT_FILE = PROJECT_DIR / "output" / "pdf_interpreter_v02_report.json"

# Heuristic thresholds in real-world meters.
WALL_MIN_LENGTH_M = 1.0
WALL_MIN_GAP_M = 0.08
WALL_MAX_GAP_M = 0.50
WALL_MIN_OVERLAP_RATIO = 0.85
WALL_ANGLE_TOL_DEG = 2.0
DOOR_MIN_WIDTH_M = 0.70
DOOR_MAX_WIDTH_M = 2.50
DOOR_COLLINEAR_TOL_M = 0.08
COLUMN_MAX_SIZE_M = 1.20


def clamp01(v):
    return max(0.0, min(1.0, float(v)))


def status_for(confidence):
    if confidence >= 0.90:
        return "auto_accept"
    if confidence >= 0.70:
        return "review_recommended"
    return "review_required"


def distance(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def midpoint(a, b):
    return [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]


def angle_deg(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0


def angle_diff(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def page_text(page):
    return page.get_text("text") or ""


def detect_scale(page):
    text = page_text(page)
    m = re.search(r"SCALE\s*1\s*:\s*(\d+(?:\.\d+)?)", text, flags=re.I)
    if not m:
        return None
    denom = float(m.group(1))
    if denom <= 0:
        return None
    return denom


def detect_level(page, fallback):
    text = page_text(page)
    m = re.search(r"LEVEL\s+(\d+)", text, flags=re.I)
    if m:
        return int(m.group(1))
    return fallback


def meters_per_pdf_point(scale_denominator):
    # 1 PDF point = 25.4/72 mm on paper.
    # At 1:N, multiply by N and convert mm -> m.
    return (25.4 / 72.0) * scale_denominator / 1000.0


def rect_dims_model(rect, mpp):
    return rect.width * mpp, rect.height * mpp


def rect_center_model(rect, origin_rect, mpp):
    x = ((rect.x0 + rect.x1) / 2.0 - origin_rect.x0) * mpp
    y = (origin_rect.y1 - (rect.y0 + rect.y1) / 2.0) * mpp
    return [x, y]


def point_to_model(pt, origin_rect, mpp):
    return [
        (float(pt.x) - origin_rect.x0) * mpp,
        (origin_rect.y1 - float(pt.y)) * mpp,
    ]


def pdf_xy_to_model(x, y, origin_rect, mpp):
    return [
        (float(x) - origin_rect.x0) * mpp,
        (origin_rect.y1 - float(y)) * mpp,
    ]


def rectangle_polygon(rect, origin_rect, mpp):
    p1 = pdf_xy_to_model(rect.x0, rect.y1, origin_rect, mpp)
    p2 = pdf_xy_to_model(rect.x1, rect.y1, origin_rect, mpp)
    p3 = pdf_xy_to_model(rect.x1, rect.y0, origin_rect, mpp)
    p4 = pdf_xy_to_model(rect.x0, rect.y0, origin_rect, mpp)
    return [p1, p2, p3, p4]


def extract_words(page, origin_rect, mpp):
    result = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        center = pdf_xy_to_model((x0 + x1) / 2.0, (y0 + y1) / 2.0, origin_rect, mpp)
        result.append({
            "text": text,
            "center": center,
            "pdf_bbox": [x0, y0, x1, y1],
        })
    return result


def nearest_text(words, center, predicate=None, max_dist=2.0):
    best = None
    for w in words:
        if predicate and not predicate(w["text"]):
            continue
        d = distance(center, w["center"])
        if d <= max_dist and (best is None or d < best[0]):
            best = (d, w)
    return best[1] if best else None


def line_overlap_ratio(a1, a2, b1, b2):
    dx = a2[0] - a1[0]
    dy = a2[1] - a1[1]
    la = math.hypot(dx, dy)
    if la <= 1e-9:
        return 0.0
    ux, uy = dx / la, dy / la

    def proj(p):
        return (p[0] - a1[0]) * ux + (p[1] - a1[1]) * uy

    bp = sorted([proj(b1), proj(b2)])
    overlap = max(0.0, min(la, bp[1]) - max(0.0, bp[0]))
    lb = distance(b1, b2)
    return overlap / max(1e-9, min(la, lb))


def pair_wall_rails(lines):
    used = set()
    pairs = []

    for i, a in enumerate(lines):
        if i in used:
            continue

        best = None
        for j in range(i + 1, len(lines)):
            if j in used:
                continue
            b = lines[j]

            if angle_diff(a["angle"], b["angle"]) > WALL_ANGLE_TOL_DEG:
                continue

            ga = LineString([a["start"], a["end"]])
            gb = LineString([b["start"], b["end"]])
            gap = ga.distance(gb)
            if not (WALL_MIN_GAP_M <= gap <= WALL_MAX_GAP_M):
                continue

            overlap = line_overlap_ratio(a["start"], a["end"], b["start"], b["end"])
            if overlap < WALL_MIN_OVERLAP_RATIO:
                continue

            score = (abs(gap - 0.20), -overlap)
            if best is None or score < best[0]:
                best = (score, j, b, gap, overlap)

        if best is None:
            continue

        _, j, b, gap, overlap = best
        used.add(i)
        used.add(j)

        # Align endpoints before averaging.
        same = distance(a["start"], b["start"]) + distance(a["end"], b["end"])
        rev = distance(a["start"], b["end"]) + distance(a["end"], b["start"])
        b1, b2 = (b["start"], b["end"]) if same <= rev else (b["end"], b["start"])

        start = midpoint(a["start"], b1)
        end = midpoint(a["end"], b2)

        pairs.append({
            "start": start,
            "end": end,
            "angle": angle_deg(start, end),
            "thickness": gap,
            "overlap_ratio": overlap,
            "source_line_indices": [i, j],
        })

    return pairs


def merge_wall_segments_for_doors(wall_segments, thin_lines, words):
    used = set()
    merged = []
    door_candidates = []

    for i, a in enumerate(wall_segments):
        if i in used:
            continue

        best = None
        for j in range(i + 1, len(wall_segments)):
            if j in used:
                continue
            b = wall_segments[j]

            if angle_diff(a["angle"], b["angle"]) > WALL_ANGLE_TOL_DEG:
                continue

            line_a = LineString([a["start"], a["end"]])
            if line_a.distance(Point(b["start"])) > DOOR_COLLINEAR_TOL_M and line_a.distance(Point(b["end"])) > DOOR_COLLINEAR_TOL_M:
                # Segment B may lie beyond A, so use infinite-line style perpendicular check.
                dx = a["end"][0] - a["start"][0]
                dy = a["end"][1] - a["start"][1]
                la = math.hypot(dx, dy)
                if la <= 1e-9:
                    continue
                perp = abs(dy * (b["start"][0] - a["start"][0]) - dx * (b["start"][1] - a["start"][1])) / la
                if perp > DOOR_COLLINEAR_TOL_M:
                    continue

            dx = a["end"][0] - a["start"][0]
            dy = a["end"][1] - a["start"][1]
            la = math.hypot(dx, dy)
            ux, uy = dx / la, dy / la

            def proj(p):
                return (p[0] - a["start"][0]) * ux + (p[1] - a["start"][1]) * uy

            a_int = sorted([0.0, la])
            b_int = sorted([proj(b["start"]), proj(b["end"])])
            intervals = sorted([a_int, b_int], key=lambda t: t[0])
            gap = intervals[1][0] - intervals[0][1]

            if not (DOOR_MIN_WIDTH_M <= gap <= DOOR_MAX_WIDTH_M):
                continue

            if best is None or abs(gap - 1.0) < abs(best[0] - 1.0):
                best = (gap, j, b, ux, uy, intervals)

        if best is None:
            merged.append({**a, "openings": []})
            used.add(i)
            continue

        gap, j, b, ux, uy, intervals = best
        used.add(i)
        used.add(j)

        # Extreme projected bounds from both segments.
        pts = [a["start"], a["end"], b["start"], b["end"]]
        projections = [((p[0] - a["start"][0]) * ux + (p[1] - a["start"][1]) * uy, p) for p in pts]
        min_t = min(t for t, _ in projections)
        max_t = max(t for t, _ in projections)
        start = [a["start"][0] + ux * min_t, a["start"][1] + uy * min_t]
        end = [a["start"][0] + ux * max_t, a["start"][1] + uy * max_t]

        # Gap center along A direction.
        first, second = intervals
        gap_center_t = (first[1] + second[0]) / 2.0
        gap_center = [a["start"][0] + ux * gap_center_t, a["start"][1] + uy * gap_center_t]

        door_label = nearest_text(
            words,
            gap_center,
            predicate=lambda t: bool(re.match(r"D\d+", t, flags=re.I)),
            max_dist=2.5,
        )

        leaf = None
        for tl in thin_lines:
            c = midpoint(tl["start"], tl["end"])
            l = distance(tl["start"], tl["end"])
            if DOOR_MIN_WIDTH_M <= l <= DOOR_MAX_WIDTH_M and distance(c, gap_center) <= 0.6:
                leaf = tl
                break

        swing_count = 0
        for tl in thin_lines:
            c = midpoint(tl["start"], tl["end"])
            if tl["width_pt"] <= 0.50 and distance(c, gap_center) <= 2.2:
                swing_count += 1

        evidence = [
            "double_line_wall_pair",
            "aligned_wall_segments",
            f"opening_gap_{gap:.2f}m",
        ]
        conf = 0.80
        if door_label:
            evidence.append(f"door_label:{door_label['text']}")
            conf += 0.08
        if leaf:
            evidence.append("door_leaf_line")
            conf += 0.07
        if swing_count >= 3:
            evidence.append("door_swing_geometry")
            conf += 0.05

        opening = {
            "center": gap_center,
            "width": gap,
            "confidence": clamp01(conf),
            "evidence": evidence,
        }

        merged.append({
            "start": start,
            "end": end,
            "angle": angle_deg(start, end),
            "thickness": (a["thickness"] + b["thickness"]) / 2.0,
            "overlap_ratio": min(a["overlap_ratio"], b["overlap_ratio"]),
            "openings": [opening],
        })

        door_candidates.append(opening)

    return merged, door_candidates


def candidate(cid, ctype, confidence, evidence, geometry=None, properties=None, source=None):
    return {
        "id": cid,
        "type": ctype,
        "confidence": round(clamp01(confidence), 3),
        "status": status_for(confidence),
        "evidence": evidence,
        "geometry": geometry or {},
        "properties": properties or {},
        "source": source or {},
    }


def interpret_page(page, page_index):
    scale = detect_scale(page)
    level = detect_level(page, page_index + 1)

    drawings = page.get_drawings()
    rect_drawings = []
    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "re":
                rect_drawings.append((item[1], d))

    if not rect_drawings:
        raise RuntimeError(f"Page {page_index + 1}: no rectangle candidates for floor boundary")

    # Explicit scale is highly preferred. Fallback is only for diagnostics.
    if scale is None:
        scale = 100.0
        scale_conf = 0.45
        scale_evidence = ["missing_explicit_scale", "fallback_1:100"]
    else:
        scale_conf = 0.99
        scale_evidence = [f"explicit_text:SCALE 1:{int(scale) if scale.is_integer() else scale}"]

    mpp = meters_per_pdf_point(scale)

    # Largest rectangle by page-space area is our walkable/floor candidate.
    origin_rect, origin_draw = max(rect_drawings, key=lambda x: x[0].width * x[0].height)
    area_w, area_h = rect_dims_model(origin_rect, mpp)

    words = extract_words(page, origin_rect, mpp)

    candidates = []
    page_tag = f"P{page_index + 1}"

    candidates.append(candidate(
        f"{page_tag}-SCALE",
        "scale",
        scale_conf,
        scale_evidence,
        properties={"denominator": scale, "meters_per_pdf_point": mpp},
        source={"page": page_index + 1},
    ))

    level_conf = 0.99 if re.search(r"LEVEL\s+\d+", page_text(page), flags=re.I) else 0.55
    candidates.append(candidate(
        f"{page_tag}-LEVEL",
        "level",
        level_conf,
        ["explicit_level_text"] if level_conf > 0.9 else ["page_order_fallback"],
        properties={"level_key": level, "z": (level - 1) * 4.0},
        source={"page": page_index + 1},
    ))

    area_conf = 0.98
    area_evidence = ["largest_closed_rectangle", f"size_{area_w:.2f}x{area_h:.2f}m"]
    if 5.0 <= area_w <= 100.0 and 5.0 <= area_h <= 100.0:
        area_conf += 0.01
    candidates.append(candidate(
        f"{page_tag}-AREA-01",
        "area",
        area_conf,
        area_evidence,
        geometry={"polygon": rectangle_polygon(origin_rect, origin_rect, mpp)},
        properties={"level_key": level},
        source={"page": page_index + 1},
    ))

    # Extract vector primitives.
    heavy_lines = []
    thin_lines = []
    circle_shapes = []

    for d in drawings:
        width_pt = float(d.get("width") or 0.0)
        for item in d.get("items", []):
            kind = item[0]
            if kind == "l":
                a = point_to_model(item[1], origin_rect, mpp)
                b = point_to_model(item[2], origin_rect, mpp)
                length = distance(a, b)
                rec = {
                    "start": a,
                    "end": b,
                    "angle": angle_deg(a, b),
                    "length": length,
                    "width_pt": width_pt,
                }
                if width_pt >= 0.80 and length >= WALL_MIN_LENGTH_M:
                    heavy_lines.append(rec)
                else:
                    thin_lines.append(rec)
            elif kind == "c":
                # Circle / ellipse from cubic Bezier path. Classify by its drawing bbox later.
                pass

        if d.get("items") and all(it[0] == "c" for it in d["items"]):
            r = d["rect"]
            w, h = rect_dims_model(r, mpp)
            if abs(w - h) <= 0.08 and 0.20 <= w <= 2.0:
                circle_shapes.append({
                    "center": rect_center_model(r, origin_rect, mpp),
                    "diameter": (w + h) / 2.0,
                    "bbox": r,
                })

    wall_segments = pair_wall_rails(heavy_lines)
    wall_segments, doors = merge_wall_segments_for_doors(wall_segments, thin_lines, words)

    # Walls.
    for idx, wall in enumerate(wall_segments, start=1):
        evidence = [
            "parallel_line_pair",
            f"thickness_{wall['thickness']:.2f}m",
            f"overlap_{wall['overlap_ratio']:.2f}",
        ]
        conf = 0.94
        if 0.12 <= wall["thickness"] <= 0.35:
            evidence.append("typical_wall_thickness")
            conf += 0.03
        if wall.get("openings"):
            evidence.append("door_opening_associated")
            conf += 0.02

        openings = []
        for op_idx, op in enumerate(wall.get("openings", []), start=1):
            openings.append({
                "name": f"Detected Door {op_idx}",
                "center": op["center"],
                "width": op["width"],
                "confidence": op["confidence"],
                "evidence": op["evidence"],
            })

        candidates.append(candidate(
            f"{page_tag}-WALL-{idx:02d}",
            "wall",
            conf,
            evidence,
            geometry={"start": wall["start"], "end": wall["end"]},
            properties={
                "level_key": level,
                "thickness": wall["thickness"],
                "height": 3.0,
                "openings": openings,
            },
            source={"page": page_index + 1},
        ))

    # Rectangles other than the floor boundary.
    internal_rects = []
    for r, d in rect_drawings:
        if r == origin_rect:
            continue
        w, h = rect_dims_model(r, mpp)
        center = rect_center_model(r, origin_rect, mpp)
        internal_rects.append({"rect": r, "w": w, "h": h, "center": center, "draw": d})

    col_count = 0
    equip_count = 0
    stair_count = 0
    unknown_count = 0

    for item in internal_rects:
        w, h, center = item["w"], item["h"], item["center"]
        if w <= 0 or h <= 0:
            continue

        up_word = nearest_text(words, center, predicate=lambda t: t.upper() in {"UP", "DN", "DOWN"}, max_dist=max(w, h) / 2.0 + 0.6)
        eq_word = nearest_text(words, center, predicate=lambda t: t.upper().startswith("EQ"), max_dist=max(w, h) / 2.0 + 0.4)

        # Count thin tread-like lines with midpoint inside rectangle.
        xmin = center[0] - w / 2.0
        xmax = center[0] + w / 2.0
        ymin = center[1] - h / 2.0
        ymax = center[1] + h / 2.0
        tread_count = 0
        for tl in thin_lines:
            c = midpoint(tl["start"], tl["end"])
            if xmin <= c[0] <= xmax and ymin <= c[1] <= ymax and 0.2 <= tl["length"] <= max(w, h) + 0.2:
                tread_count += 1

        if up_word and tread_count >= 5 and max(w, h) >= 2.0:
            stair_count += 1
            conf = 0.89
            evidence = [
                "enclosing_rectangle",
                f"parallel_treads:{tread_count}",
                f"direction_text:{up_word['text']}",
                "step_count_not_explicit",
            ]
            candidates.append(candidate(
                f"{page_tag}-STAIR-{stair_count:02d}",
                "stairway",
                conf,
                evidence,
                geometry={"polygon": rectangle_polygon(item["rect"], origin_rect, mpp)},
                properties={
                    "start_level": level,
                    "end_level": level + 1,
                    "steps": 24,
                    "steps_source": "default_assumption",
                    "thickness": 0.20,
                    "show_balustrade": True,
                },
                source={"page": page_index + 1},
            ))
            continue

        if eq_word:
            equip_count += 1
            candidates.append(candidate(
                f"{page_tag}-EQUIP-{equip_count:02d}",
                "equipment",
                0.94,
                ["closed_rectangle", f"near_text:{eq_word['text']}", f"size_{w:.2f}x{h:.2f}m"],
                geometry={"polygon": rectangle_polygon(item["rect"], origin_rect, mpp)},
                properties={"level_key": level, "height": 1.20},
                source={"page": page_index + 1},
            ))
            continue

        if max(w, h) <= COLUMN_MAX_SIZE_M and min(w, h) >= 0.20 and abs(w - h) <= 0.45:
            col_count += 1
            conf = 0.95 if abs(w - h) <= 0.15 else 0.88
            candidates.append(candidate(
                f"{page_tag}-COLUMN-{col_count:02d}",
                "column",
                conf,
                ["small_closed_rectangle", f"size_{w:.2f}x{h:.2f}m"],
                geometry={"center": center},
                properties={
                    "level_key": level,
                    "shape": "rectangle",
                    "width": w,
                    "depth": h,
                    "rotation_deg": 0.0,
                    "height": 3.0,
                },
                source={"page": page_index + 1},
            ))
            continue

        # Anything else remains a candidate for human review.
        unknown_count += 1
        candidates.append(candidate(
            f"{page_tag}-UNKNOWN-{unknown_count:02d}",
            "unknown_rectangle",
            0.52,
            ["closed_rectangle", f"size_{w:.2f}x{h:.2f}m", "no_semantic_text", "not_column_sized"],
            geometry={"polygon": rectangle_polygon(item["rect"], origin_rect, mpp)},
            properties={"level_key": level},
            source={"page": page_index + 1},
        ))

    # Circular columns.
    for circle in circle_shapes:
        col_count += 1
        conf = 0.96 if 0.30 <= circle["diameter"] <= 1.20 else 0.78
        candidates.append(candidate(
            f"{page_tag}-COLUMN-{col_count:02d}",
            "column",
            conf,
            ["closed_circular_vector_path", f"diameter_{circle['diameter']:.2f}m"],
            geometry={"center": circle["center"]},
            properties={
                "level_key": level,
                "shape": "circle",
                "diameter": circle["diameter"],
                "height": 3.0,
            },
            source={"page": page_index + 1},
        ))

    return {
        "page": page_index + 1,
        "level_key": level,
        "scale_denominator": scale,
        "meters_per_pdf_point": mpp,
        "floor_bbox_pdf": [origin_rect.x0, origin_rect.y0, origin_rect.x1, origin_rect.y1],
        "floor_size_m": [area_w, area_h],
        "candidates": candidates,
        "diagnostics": {
            "drawings": len(drawings),
            "rectangles": len(rect_drawings),
            "heavy_lines": len(heavy_lines),
            "thin_lines": len(thin_lines),
            "wall_segments": len(wall_segments),
            "door_openings": len(doors),
            "circle_shapes": len(circle_shapes),
        },
    }


def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(PDF_FILE)

    doc = fitz.open(PDF_FILE)
    pages = [interpret_page(page, i) for i, page in enumerate(doc)]

    all_candidates = [c for p in pages for c in p["candidates"]]
    review = [c for c in all_candidates if c["status"] != "auto_accept"]

    counts = {}
    for c in all_candidates:
        counts[c["type"]] = counts.get(c["type"], 0) + 1

    model = {
        "schema_version": "0.2",
        "source_file": str(PDF_FILE),
        "strategy": "vector_geometry_plus_text_heuristics",
        "pages": pages,
        "summary": {
            "candidate_count": len(all_candidates),
            "review_count": len(review),
            "counts_by_type": counts,
        },
    }

    review_model = {
        "source_file": str(PDF_FILE),
        "review_count": len(review),
        "items": review,
    }

    report = {
        "source_file": str(PDF_FILE),
        "pages": len(pages),
        "candidate_count": len(all_candidates),
        "review_count": len(review),
        "counts_by_type": counts,
        "page_diagnostics": [p["diagnostics"] for p in pages],
        "status": "REVIEW" if review else "PASS",
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE_FILE.write_text(json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8")
    REVIEW_FILE.write_text(json.dumps(review_model, indent=2, ensure_ascii=False), encoding="utf-8")
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("PDF Vector Interpreter v0.2")
    print("=" * 60)
    print("Source:", PDF_FILE)
    print("Pages:", len(pages))
    print("Candidates:", len(all_candidates))
    print("Review queue:", len(review))
    print()
    for ctype, count in sorted(counts.items()):
        print(f"{ctype:<20}: {count}")
    print()
    for p in pages:
        print(
            f"Page {p['page']} | Level={p['level_key']} | "
            f"Scale=1:{p['scale_denominator']} | "
            f"Floor={p['floor_size_m'][0]:.2f} x {p['floor_size_m'][1]:.2f} m | "
            f"Walls={p['diagnostics']['wall_segments']} | Doors={p['diagnostics']['door_openings']}"
        )
    print()
    print("Candidate model:", CANDIDATE_FILE)
    print("Review queue   :", REVIEW_FILE)
    print("Report         :", REPORT_FILE)


if __name__ == "__main__":
    main()
