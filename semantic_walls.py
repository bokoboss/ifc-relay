"""Walls and wall openings for the pedestrian (semantic) model: wall axes from
footprints, door/opening relationships and shapes, unfilled-opening
classification, and copying multi-storey walls to each storey they cross."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from shapely.geometry import Polygon

from ifc_service import is_a
from semantic_geometry import EPS, _farthest_pair, largest_polygon, mesh_footprint


def axis_from_footprint(poly: Polygon) -> dict[str, Any]:
    """Approximate a wall/column footprint using its minimum rotated rectangle."""
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:-1]
    if len(coords) != 4:
        raise ValueError("minimum rotated rectangle did not produce four corners")

    def dist(p: tuple[float, float], q: tuple[float, float]) -> float:
        return math.hypot(q[0] - p[0], q[1] - p[1])

    l01 = dist(coords[0], coords[1])
    l12 = dist(coords[1], coords[2])

    def mid(p: tuple[float, float], q: tuple[float, float]) -> tuple[float, float]:
        return ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)

    if l01 >= l12:
        start = mid(coords[3], coords[0])
        end = mid(coords[1], coords[2])
        thickness = l12
        major = l01
    else:
        start = mid(coords[0], coords[1])
        end = mid(coords[2], coords[3])
        thickness = l01
        major = l12

    # Stable orientation makes regression output deterministic.
    if end < start:
        start, end = end, start

    angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))

    return {
        "start": [float(start[0]), float(start[1])],
        "end": [float(end[0]), float(end[1])],
        "length": float(major),
        "thickness": float(max(thickness, 0.001)),
        "rotation_deg": float(angle),
        "rectangle": rect,
    }


def project_point_to_axis(
    point_xy: tuple[float, float] | list[float],
    start: list[float],
    end: list[float],
) -> tuple[float, float, list[float]]:
    sx, sy = start
    ex, ey = end
    px, py = float(point_xy[0]), float(point_xy[1])
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length <= EPS:
        return 0.0, float("inf"), [sx, sy]
    ux = dx / length
    uy = dy / length
    t = (px - sx) * ux + (py - sy) * uy
    qx = sx + ux * t
    qy = sy + uy * t
    perp = math.hypot(px - qx, py - qy)
    return t, perp, [qx, qy]


def split_wall_axis(
    start: list[float],
    end: list[float],
    openings: list[dict[str, Any]],
    min_segment: float = 0.02,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a logical wall centerline around door openings.

    Returns physical segments and normalized opening intervals.
    """
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length <= EPS:
        return [], []

    ux = dx / length
    uy = dy / length
    intervals: list[dict[str, Any]] = []

    for opening in openings:
        center = opening["center"]
        width = max(float(opening["width"]), 0.01)
        t, perp, projected = project_point_to_axis(center, start, end)
        a = max(0.0, t - width / 2.0)
        b = min(length, t + width / 2.0)
        if b - a <= EPS:
            continue
        intervals.append(
            {
                **opening,
                "t_start": a,
                "t_end": b,
                "perpendicular_distance": perp,
                "projected_center": projected,
            }
        )

    intervals.sort(key=lambda x: x["t_start"])

    # Merge overlapping openings. Keep source door identifiers for audit.
    merged: list[dict[str, Any]] = []
    for item in intervals:
        if not merged or item["t_start"] > merged[-1]["t_end"] + EPS:
            merged.append({**item, "source_doors": [item.get("door_global_id")]})
        else:
            merged[-1]["t_end"] = max(merged[-1]["t_end"], item["t_end"])
            merged[-1]["source_doors"].append(item.get("door_global_id"))

    segments: list[dict[str, Any]] = []
    cursor = 0.0
    for gap in merged:
        if gap["t_start"] - cursor >= min_segment:
            segments.append(
                {
                    "start": [sx + ux * cursor, sy + uy * cursor],
                    "end": [sx + ux * gap["t_start"], sy + uy * gap["t_start"]],
                }
            )
        cursor = max(cursor, gap["t_end"])

    if length - cursor >= min_segment:
        segments.append(
            {
                "start": [sx + ux * cursor, sy + uy * cursor],
                "end": [ex, ey],
            }
        )

    return segments, intervals


def _opening_shape(model: Any, opening: Any) -> tuple[Polygon, float, float] | None:
    """Return (XY footprint, z_min, z_max) of an IfcOpeningElement."""
    import ifcopenshell.geom

    if getattr(opening, "Representation", None) is None:
        return None

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    try:
        shape = ifcopenshell.geom.create_shape(settings, opening)
        verts = [float(v) for v in shape.geometry.verts]
        faces = [int(v) for v in shape.geometry.faces]
    except Exception:
        return None

    poly = largest_polygon(mesh_footprint(verts, faces))
    if poly is None or not verts:
        return None
    zs = verts[2::3]
    return poly, min(zs), max(zs)


def _opening_shape_polygon(model: Any, opening: Any) -> Polygon | None:
    shape = _opening_shape(model, opening)
    return shape[0] if shape is not None else None


def _filled_opening_ids(model: Any) -> set[int]:
    ids: set[int] = set()
    for rel in model.by_type("IfcRelFillsElement"):
        opening = getattr(rel, "RelatingOpeningElement", None)
        if opening is not None:
            ids.add(int(opening.id()))
    return ids


# Unfilled wall openings that look like walkable passages (never applied
# automatically; the engineer includes them by opening GlobalId).
PASSAGE_MAX_SILL = 0.30


PASSAGE_MIN_HEIGHT = 1.80


PASSAGE_MIN_WIDTH = 0.60


def classify_unfilled_opening(width: float, height: float, sill: float) -> str:
    """'passage_candidate' when the opening could be walked through."""
    if sill <= PASSAGE_MAX_SILL and height >= PASSAGE_MIN_HEIGHT and width >= PASSAGE_MIN_WIDTH:
        return "passage_candidate"
    return "not_passage"


# Wall footprints less convex than this (L/T/curved) are exported as polygon
# obstacles instead of a single rectangular centreline wall. Mitred ends keep
# the footprint convex, so ordinary straight walls are unaffected.
WALL_POLYGON_SOLIDITY = 0.95


def wall_footprint_solidity(footprint: Polygon) -> float:
    hull = footprint.convex_hull
    return float(footprint.area / hull.area) if hull.area > EPS else 1.0


def _door_relationships(model: Any) -> tuple[dict[int, Any], dict[int, Any]]:
    door_to_opening: dict[int, Any] = {}
    opening_to_host: dict[int, Any] = {}

    for rel in model.by_type("IfcRelFillsElement"):
        opening = getattr(rel, "RelatingOpeningElement", None)
        fill = getattr(rel, "RelatedBuildingElement", None)
        if opening is not None and fill is not None and is_a(fill, "IfcDoor"):
            door_to_opening[int(fill.id())] = opening

    for rel in model.by_type("IfcRelVoidsElement"):
        host = getattr(rel, "RelatingBuildingElement", None)
        opening = getattr(rel, "RelatedOpeningElement", None)
        if host is not None and opening is not None:
            opening_to_host[int(opening.id())] = host

    return door_to_opening, opening_to_host


# An element continues onto a storey when it rises at least this far above that
# storey's floor (it blocks walking height there).
STOREY_CONTINUATION_MIN = 1.0


def wall_storey_bands(bottom: float, top: float, base_level: int,
                      storey_z: list[tuple[float, int]]) -> list[tuple[int, float, float]]:
    """(level, z_from, z_to) pieces of a wall: its own storey plus every storey it
    rises at least STOREY_CONTINUATION_MIN above. One band for ordinary walls."""
    crossed = [(z, k) for z, k in storey_z
               if k != base_level and z > bottom + 0.5 and top - z >= STOREY_CONTINUATION_MIN]
    if not crossed:
        return [(base_level, bottom, top)]
    cuts = [bottom] + [z for z, _ in crossed] + [top]
    levels = [base_level] + [k for _, k in crossed]
    return [(levels[i], cuts[i], cuts[i + 1]) for i in range(len(levels))]


def opening_at_walking_height(opening: dict[str, Any], floor_z: float, is_base: bool) -> bool:
    """True when the opening is open 1 m above this storey's floor (door/passage height).
    Openings without height information only cut the wall's own (base) storey."""
    z_min, z_max = opening.get("z_min"), opening.get("z_max")
    if z_min is None or z_max is None:
        return is_base
    probe = floor_z + 1.0
    return z_min < probe < z_max


def replicate_across_storeys(
    walls: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    obstacles: list[dict[str, Any]],
    storeys: list[dict[str, Any]],
    level_z_by_key: dict[int, float],
) -> tuple[int, int, int]:
    """Copy walls, columns and obstacles that span several storeys onto every storey they cross.

    Vissim obstacles act only on their own level, so a 3-storey exterior or core wall
    assigned to the ground floor would otherwise be missing on the floors above.
    The original keeps its level with its height trimmed to the next crossed storey;
    each copy sits on the crossed storey with z offset 0. Wall copies span the whole
    wall without the lower storey's door gaps (closed is the safe side; reviewed via warning).
    Returns (elements replicated, copies made, wall copies without openings).
    """
    zs = sorted((float(level_z_by_key[int(lv["key"])]), int(lv["key"]), lv.get("name", "")) for lv in storeys)
    replicated = copies = closed_wall_copies = 0
    seen_wall_logical: set[tuple[Any, int, int]] = set()

    def crossed(rec: dict[str, Any]) -> list[tuple[float, int, str]]:
        base_key = int(rec["level_key"])
        if base_key not in level_z_by_key:
            return []
        bottom = level_z_by_key[base_key] + float(rec.get("z_offset") or 0.0)
        top = bottom + float(rec.get("height") or 0.0)
        return [(z, k, n) for z, k, n in zs if k != base_key and z > bottom + 0.5 and top - z >= STOREY_CONTINUATION_MIN]

    # Line walls: group the door-split segments of one logical wall.
    groups: dict[tuple[Any, int], list[dict[str, Any]]] = defaultdict(list)
    for w in walls:
        groups[(w.get("logical_wall_global_id") or id(w), int(w["level_key"]))].append(w)
    new_walls: list[dict[str, Any]] = []
    for (logical, base_key), segs in groups.items():
        if any(seg.get("storey_split") for seg in segs):
            continue
        targets = crossed(segs[0])
        if not targets:
            continue
        replicated += 1
        bottom = level_z_by_key[base_key] + float(segs[0].get("z_offset") or 0.0)
        top = bottom + float(segs[0].get("height") or 0.0)
        for seg in segs:
            seg["height"] = round(targets[0][0] - bottom, 5)
            seg["continues_on_levels"] = [k for _, k, _ in targets]
        a, b = _farthest_pair([seg["start"] for seg in segs] + [seg["end"] for seg in segs])
        base_name = str(segs[0]["name"]).split(" [segment ")[0]
        for i, (z, key, name) in enumerate(targets):
            z_next = targets[i + 1][0] if i + 1 < len(targets) else top
            copy = {k: v for k, v in segs[0].items() if k not in ("key", "start", "end", "name", "continues_on_levels")}
            copy.update({"name": f"{base_name} [continues on {name}]", "level_key": key, "z_offset": 0.0,
                         "start": list(a), "end": list(b), "height": round(z_next - z, 5),
                         "replicated_from_level": base_key})
            new_walls.append(copy)
            copies += 1
            if len(segs) > 1:
                closed_wall_copies += 1
    walls.extend(new_walls)

    for collection in (columns, obstacles):
        extra: list[dict[str, Any]] = []
        for rec in collection:
            if rec.get("generated") or rec.get("type") == "walkable_void_mask" or rec.get("storey_split"):
                continue
            targets = crossed(rec)
            if not targets:
                continue
            replicated += 1
            base_key = int(rec["level_key"])
            bottom = level_z_by_key[base_key] + float(rec.get("z_offset") or 0.0)
            top = bottom + float(rec.get("height") or 0.0)
            rec["height"] = round(targets[0][0] - bottom, 5)
            rec["continues_on_levels"] = [k for _, k, _ in targets]
            for i, (z, key, name) in enumerate(targets):
                z_next = targets[i + 1][0] if i + 1 < len(targets) else top
                copy = {k: v for k, v in rec.items() if k not in ("key", "continues_on_levels")}
                copy.update({"name": f"{rec['name']} [continues on {name}]", "level_key": key, "z_offset": 0.0,
                             "height": round(z_next - z, 5), "replicated_from_level": base_key})
                extra.append(copy)
                copies += 1
        collection.extend(extra)
    return replicated, copies, closed_wall_copies
