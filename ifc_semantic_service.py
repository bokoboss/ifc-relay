from __future__ import annotations

from version import ENGINE_CONTRACT, SEMANTIC_SCHEMA_VERSION

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from ifc_service import (
    _imports,
    entity_name,
    global_id,
    is_a,
    recommendation,
    resolve_storey,
    storey_lookup,
)
from ifc_vertical_service import (
    INTERMEDIATE_LANDING_THRESHOLD,
    LANDING_LEVEL_KEY_START,
    LEVEL_SNAP_TOLERANCE,
    build_vertical_connections,
    children_map,
    cluster_landing_levels,
    collect_vertical_units,
    is_intermediate_landing,
)


EPS = 1e-8
# Storey elevation vs. floor-slab top difference that is reported as a datum warning.
STOREY_DATUM_WARNING = 0.05
# Non-landing floor slabs within this distance of the storey floor are merged into
# it with a warning (steps, sunken wet areas, finishes). Further away they are left
# out of the walkable floor until the engineer includes them (sunscreens, canopies,
# mezzanines) - IFC predefined type FLOOR alone is not proof that a slab is walkable.
OFF_LEVEL_MERGE_MAX = 0.40
# Unfilled wall openings that look like walkable passages (never applied
# automatically; the engineer includes them by opening GlobalId).
PASSAGE_MAX_SILL = 0.30
PASSAGE_MIN_HEIGHT = 1.80
PASSAGE_MIN_WIDTH = 0.60
# Wall footprints less convex than this (L/T/curved) are exported as polygon
# obstacles instead of a single rectangular centreline wall. Mitred ends keep
# the footprint convex, so ordinary straight walls are unaffected.
WALL_POLYGON_SOLIDITY = 0.95
# Interior rings of merged floor regions smaller than this are slab-joint
# precision gaps, not pedestrian-relevant voids; no void mask is generated.
MIN_VOID_MASK_AREA = 0.05


# Default first keys per engine-facing collection. They are kept whenever the
# collection fits below the next default, so small models keep their keys.
DEFAULT_KEY_STARTS: tuple[tuple[str, int], ...] = (
    ("areas", 1001),
    ("walls", 1101),
    ("columns", 1301),
    ("obstacles", 1401),
    ("vertical_connections", 2001),
)
KEY_BLOCK = 1000


def assign_key_ranges(collections: dict[str, list[dict[str, Any]]]) -> dict[str, list[int]]:
    """Give every engine object a key that is unique across all collections.

    v0.4.1a used fixed starts (areas 1001, walls 1101, columns 1301,
    obstacles 1401, vertical 2001), so >100 areas or >200 wall segments
    overlapped the next range. Each collection now starts at its default when
    that is free, otherwise at the next free block of 1000 (x001). Order inside
    each collection is preserved. Returns ``{name: [first, last]}``.
    """
    ranges: dict[str, list[int]] = {}
    next_free = 0
    for name, default in DEFAULT_KEY_STARTS:
        items = collections.get(name) or []
        start = default
        if start < next_free:
            start = ((next_free - 1) // KEY_BLOCK + 1) * KEY_BLOCK + 1
        for i, item in enumerate(items):
            item["key"] = start + i
        if items:
            ranges[name] = [start, start + len(items) - 1]
            next_free = start + len(items)
        else:
            next_free = max(next_free, start)
    return ranges


def effective_status(entity: Any, overrides: dict[str, str]) -> str:
    guid = global_id(entity)
    if guid and guid in overrides:
        return overrides[guid]
    return recommendation(entity)[0]


def mesh_footprint(vertices: list[float], indices: list[int]) -> Polygon | MultiPolygon | None:
    """Return a 2D XY projection of triangulated mesh geometry.

    IfcOpenShell geometry output is in metres by default unless convert-back-units
    is explicitly enabled. v0.2 does not enable that setting, so these coordinates
    can be sent directly to the metre-based semantic engine.
    """
    if not vertices or not indices:
        return None

    coords = [
        (float(vertices[i]), float(vertices[i + 1]), float(vertices[i + 2]))
        for i in range(0, len(vertices), 3)
    ]

    tris: list[Polygon] = []
    for i in range(0, len(indices), 3):
        try:
            a = coords[int(indices[i])]
            b = coords[int(indices[i + 1])]
            c = coords[int(indices[i + 2])]
        except (IndexError, ValueError):
            continue

        poly = Polygon([(a[0], a[1]), (b[0], b[1]), (c[0], c[1])])
        if poly.is_valid and poly.area > EPS:
            tris.append(poly)

    if not tris:
        return None

    geom = unary_union(tris)
    if not geom.is_valid:
        geom = geom.buffer(0)

    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom

    if isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if isinstance(g, Polygon) and g.area > EPS]
        if not polys:
            return None
        merged = unary_union(polys)
        if isinstance(merged, (Polygon, MultiPolygon)):
            return merged

    return None


def largest_polygon(geom: Polygon | MultiPolygon | None) -> Polygon | None:
    if geom is None:
        return None
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda g: g.area, default=None)
    return None


def polygon_points(poly: Polygon, digits: int = 5) -> list[list[float]]:
    # Preserve the source outline but remove the closing duplicate coordinate.
    simplified = poly.simplify(1e-5, preserve_topology=True)
    if not isinstance(simplified, Polygon):
        simplified = poly
    coords = list(simplified.exterior.coords)[:-1]
    return [[round(float(x), digits), round(float(y), digits)] for x, y in coords]


def polygon_components(geom: Polygon | MultiPolygon | None) -> list[Polygon]:
    if geom is None:
        return []
    if isinstance(geom, Polygon):
        return [geom] if geom.area > EPS else []
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if isinstance(g, Polygon) and g.area > EPS]
    return []


def precision_clean_polygon(poly: Polygon, grid_size: float = 0.005) -> Polygon | MultiPolygon | None:
    """Snap floor-panel geometry to a small metric grid before union."""
    geom: Any = poly
    try:
        from shapely import set_precision
        geom = set_precision(geom, grid_size=grid_size)
    except Exception:
        pass
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom if isinstance(geom, (Polygon, MultiPolygon)) else None


# Viswalk connects walkable elements only where they touch or overlap (Vissim
# manual, "Modeling construction elements"); any gap - even a slab joint of a few
# millimetres - splits the walking ground and pedestrians cannot cross it.
# Gaps narrower than this between slab pieces of one level are closed.
WALKABLE_GAP_CLOSE = 0.05
# IfcPlate/IfcMember block walking only where they stand in the walking zone:
# a plate whose top is below this (a floor deck) or whose bottom is above this
# (a canopy, a ceiling panel) relative to its level is not an obstacle.
PLATE_MIN_TOP = 0.30
PLATE_MAX_BOTTOM = 2.00


def merge_walkable_components(components: list[Polygon], grid_size: float = 0.005,
                              close_gap: float = WALKABLE_GAP_CLOSE,
                              stats: dict[str, int] | None = None) -> list[Polygon]:
    cleaned: list[Polygon] = []
    for poly in components:
        cleaned.extend(polygon_components(precision_clean_polygon(poly, grid_size=grid_size)))
    if not cleaned:
        return []
    merged = unary_union(cleaned)
    if not merged.is_valid:
        merged = merged.buffer(0)
    before = len(polygon_components(merged))
    if close_gap > 0 and before > 1:
        # Morphological closing with square joins: bridges gaps narrower than
        # close_gap, leaves straight outer edges and wider openings unchanged.
        closed = merged.buffer(close_gap / 2, join_style=2, mitre_limit=2.0).buffer(
            -close_gap / 2, join_style=2, mitre_limit=2.0)
        if not closed.is_empty:
            closed = closed if closed.is_valid else closed.buffer(0)
            after = len(polygon_components(closed))
            if after < before:
                merged = closed
                if stats is not None:
                    stats["gaps_closed"] = stats.get("gaps_closed", 0) + (before - after)
    return polygon_components(merged)


def hole_polygons(poly: Polygon) -> list[Polygon]:
    result: list[Polygon] = []
    for ring in poly.interiors:
        candidate = Polygon(ring)
        if candidate.is_valid and candidate.area > EPS:
            result.append(candidate)
    return result


def mesh_bounds(item: dict[str, Any]) -> tuple[list[float], list[float]]:
    bbox = item.get("bounds") or {}
    return (
        [float(v) for v in bbox.get("min", [0.0, 0.0, 0.0])],
        [float(v) for v in bbox.get("max", [0.0, 0.0, 0.0])],
    )


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


def classify_unfilled_opening(width: float, height: float, sill: float) -> str:
    """'passage_candidate' when the opening could be walked through."""
    if sill <= PASSAGE_MAX_SILL and height >= PASSAGE_MIN_HEIGHT and width >= PASSAGE_MIN_WIDTH:
        return "passage_candidate"
    return "not_passage"


def split_out_holes(poly: Polygon) -> list[Polygon]:
    """Split a polygon with interior rings into hole-free pieces.

    Engine obstacles are written from the exterior ring only, so a closed
    wall loop (one IfcWall around a shaft) would otherwise become a solid
    block. Each hole is removed by cutting along a vertical line through it.
    """
    from shapely.geometry import LineString
    from shapely.ops import split

    done: list[Polygon] = []
    queue: list[Polygon] = [poly]
    guard = 0
    while queue and guard < 1000:
        guard += 1
        current = queue.pop()
        if not current.interiors:
            if current.area > EPS:
                done.append(current)
            continue
        hole = Polygon(current.interiors[0])
        cx = hole.representative_point().x
        miny, maxy = current.bounds[1], current.bounds[3]
        cutter = LineString([(cx, miny - 1.0), (cx, maxy + 1.0)])
        pieces = [g for g in split(current, cutter).geoms if isinstance(g, Polygon)]
        if len(pieces) < 2:
            done.append(Polygon(current.exterior))  # cannot split; keep outline
            continue
        queue.extend(pieces)
    return done


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


def _roof_child_ids(model: Any) -> set[int]:
    ids: set[int] = set()
    for rel in model.by_type("IfcRelAggregates"):
        parent = getattr(rel, "RelatingObject", None)
        if parent is None or not is_a(parent, "IfcRoof"):
            continue
        for child in getattr(rel, "RelatedObjects", None) or []:
            try:
                ids.add(int(child.id()))
            except Exception:
                pass
    return ids


def _parent_map(model: Any) -> dict[int, Any]:
    result: dict[int, Any] = {}
    for rel in model.by_type("IfcRelAggregates"):
        parent = getattr(rel, "RelatingObject", None)
        for child in getattr(rel, "RelatedObjects", None) or []:
            try:
                result[int(child.id())] = parent
            except Exception:
                pass
    return result


def _mesh_item_map(geometry_payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(item["entity_id"]): item
        for item in geometry_payload.get("elements", [])
        if item.get("entity_id") is not None
    }



def area_weighted_median(values: list[tuple[float, float]]) -> float:
    """Median of z values weighted by footprint area; plain median if all areas are zero."""
    values = sorted(values)
    total = sum(max(a, 0.0) for _, a in values)
    if total <= 0:
        return values[len(values) // 2][0]
    acc = 0.0
    for z, a in values:
        acc += max(a, 0.0)
        if acc >= total / 2:
            return z
    return values[-1][0]


# An element continues onto a storey when it rises at least this far above that
# storey's floor (it blocks walking height there).
STOREY_CONTINUATION_MIN = 1.0


def _farthest_pair(points: list[list[float]]) -> tuple[list[float], list[float]]:
    best = (points[0], points[-1])
    best_d = -1.0
    for i, a in enumerate(points):
        for b in points[i + 1:]:
            d = math.dist(a, b)
            if d > best_d:
                best, best_d = (a, b), d
    return best



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


def trim_ramp_end_overlaps(vertical_connections: list[dict[str, Any]],
                           areas: list[dict[str, Any]], obstacles: list[dict[str, Any]] | None = None,
                           overlap: float = 0.10) -> int:
    """Extend a ramp beyond its true flight only at ends whose level area does not
    already lie under that end.

    The Engine needs each ramp end to overlap its level's walkable area. A flight
    starting on a floor already overlaps it (the floor continues under the stair);
    only an end meeting a slab edge (top of the stair, landing edge) needs the
    extension. Extending both ends made the Vissim run 0.20 m longer than the IFC
    flight. Returns the number of ends no longer extended.
    """
    from shapely.geometry import Polygon as _P

    by_level: dict[int, Any] = {}
    for a in areas:
        poly = _P(a["polygon"])
        by_level[int(a["level_key"])] = unary_union([by_level[int(a["level_key"])], poly]) \
            if int(a["level_key"]) in by_level else poly
    # Areas are exported without holes; floor openings (stair wells) are blocked by
    # generated void-mask obstacles instead, so they do not count as floor here.
    for o in obstacles or []:
        if o.get("type") == "walkable_void_mask" and int(o["level_key"]) in by_level and o.get("polygon"):
            by_level[int(o["level_key"])] = by_level[int(o["level_key"])].difference(_P(o["polygon"]))
    trimmed = 0
    for vc in vertical_connections:
        be, te = vc.get("bottom_edge"), vc.get("top_edge")
        if not be or not te or vc.get("polygon_order") != "bottom_edge_first":
            continue
        bc = ((be[0][0] + be[1][0]) / 2, (be[0][1] + be[1][1]) / 2)
        tc = ((te[0][0] + te[1][0]) / 2, (te[0][1] + te[1][1]) / 2)
        length = math.dist(bc, tc)
        if length <= 1e-6:
            continue
        ux, uy = (tc[0] - bc[0]) / length, (tc[1] - bc[1]) / length
        depth = min(overlap, length / 4)

        def covered(edge, sign, level):
            area = by_level.get(int(level))
            if area is None:
                return False
            a, b = edge
            strip = _P([a, b, (b[0] + sign * ux * depth, b[1] + sign * uy * depth),
                        (a[0] + sign * ux * depth, a[1] + sign * uy * depth)])
            return strip.area > 0 and strip.intersection(area).area >= 0.9 * strip.area

        ob = 0.0 if covered(be, +1, vc["start_level"]) else overlap
        ot = 0.0 if covered(te, -1, vc["end_level"]) else overlap
        trimmed += (ob == 0.0) + (ot == 0.0)
        vc["polygon"] = [
            [round(be[0][0] - ux * ob, 5), round(be[0][1] - uy * ob, 5)],
            [round(be[1][0] - ux * ob, 5), round(be[1][1] - uy * ob, 5)],
            [round(te[0][0] + ux * ot, 5), round(te[0][1] + uy * ot, 5)],
            [round(te[1][0] + ux * ot, 5), round(te[1][1] + uy * ot, 5)],
        ]
        vc["end_overlap"] = {"bottom": ob, "top": ot}
    return trimmed

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

def build_semantic_model(
    path: Path,
    geometry_payload: dict[str, Any],
    selection_overrides: dict[str, str] | None = None,
    manual_edits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert reviewed IFC geometry to Geometry Engine v0.3 input.

    The converter is intentionally deterministic. AI/review decides inclusion,
    while this function performs geometry conversion and validation-oriented
    simplification.
    """
    selection_overrides = dict(selection_overrides or {})
    ifcopenshell, util_element, util_unit = _imports()
    model = ifcopenshell.open(str(path))
    unit_scale = float(util_unit.calculate_unit_scale(model))
    lookup = storey_lookup(model)
    mesh_by_id = _mesh_item_map(geometry_payload)
    roof_children = _roof_child_ids(model)
    parent_lookup = _parent_map(model)

    warnings: list[str] = []
    excluded_detail: list[dict[str, Any]] = []

    # ---------------------------------------------------------
    # Levels
    # ---------------------------------------------------------
    storeys = list(model.by_type("IfcBuildingStorey"))
    storeys.sort(
        key=lambda x: float(getattr(x, "Elevation", 0.0) or 0.0)
    )

    levels: list[dict[str, Any]] = []
    level_key_by_storey_id: dict[int, int] = {}
    level_z_by_key: dict[int, float] = {}

    for idx, storey in enumerate(storeys, start=1):
        elevation = float(getattr(storey, "Elevation", 0.0) or 0.0) * unit_scale
        level_key_by_storey_id[int(storey.id())] = idx
        level_z_by_key[idx] = elevation
        levels.append(
            {
                "key": idx,
                "name": entity_name(storey, f"Level {idx}"),
                "z": round(elevation, 6),
                "ifc_global_id": global_id(storey),
                "ifc_entity_id": int(storey.id()),
            }
        )

    level_name_by_key = {int(level["key"]): str(level["name"]) for level in levels}

    def resolve_level_key(entity: Any) -> int | None:
        storey = resolve_storey(entity, lookup, util_element)
        if storey is None:
            return None
        return level_key_by_storey_id.get(int(storey.id()))

    # ---------------------------------------------------------
    # Door openings and host-wall relationships
    # ---------------------------------------------------------
    door_to_opening, opening_to_host = _door_relationships(model)
    openings_by_wall_id: dict[int, list[dict[str, Any]]] = {}
    included_door_count = 0
    door_openings_applied = 0

    # Machine-readable findings for the checklist (ARCH-01): code + object ids +
    # metrics. The English warnings stay for people; nothing parses them.
    diagnostics: list[dict[str, Any]] = []

    def diag(code: str, ids: list[str] | None = None, **metrics: Any) -> None:
        diagnostics.append({"code": code, "ids": [str(i) for i in (ids or []) if i], **metrics})

    for door in model.by_type("IfcDoor"):
        if effective_status(door, selection_overrides) != "include":
            continue
        included_door_count += 1
        opening = door_to_opening.get(int(door.id()))
        if opening is None:
            warnings.append(
                f"Door {global_id(door) or door.id()} is included but has no IfcRelFillsElement opening relationship."
            )
            diag("door_not_converted", [global_id(door) or str(door.id())], reason="no_opening_relationship")
            continue
        host = opening_to_host.get(int(opening.id()))
        if host is None or not is_a(host, "IfcWall"):
            warnings.append(
                f"Door {global_id(door) or door.id()} opening is not hosted by an IfcWall."
            )
            diag("door_not_converted", [global_id(door) or str(door.id())], reason="host_not_wall")
            continue

        opening_shape = _opening_shape(model, opening)
        opening_poly = opening_shape[0] if opening_shape else None
        door_mesh = mesh_by_id.get(int(door.id()))
        if opening_shape:
            door_z = (opening_shape[1], opening_shape[2])
        elif door_mesh is not None:
            _dmin, _dmax = mesh_bounds(door_mesh)
            door_z = (_dmin[2], _dmax[2])
        else:
            door_z = (None, None)

        if opening_poly is not None:
            center = [float(opening_poly.centroid.x), float(opening_poly.centroid.y)]
            open_axis = axis_from_footprint(opening_poly)
            inferred_width = max(open_axis["length"], open_axis["thickness"])
        elif door_mesh is not None:
            bbmin, bbmax = mesh_bounds(door_mesh)
            center = [(bbmin[0] + bbmax[0]) / 2.0, (bbmin[1] + bbmax[1]) / 2.0]
            inferred_width = max(bbmax[0] - bbmin[0], bbmax[1] - bbmin[1])
        else:
            warnings.append(
                f"Door {global_id(door) or door.id()} has no usable opening or mesh geometry."
            )
            diag("door_not_converted", [global_id(door) or str(door.id())], reason="no_geometry")
            continue

        overall_width = getattr(door, "OverallWidth", None)
        if overall_width is not None:
            width = float(overall_width) * unit_scale
        else:
            width = float(inferred_width)

        if width <= 0.05:
            warnings.append(
                f"Door {global_id(door) or door.id()} has suspicious width {width:.3f} m; using inferred opening width."
            )
            width = float(inferred_width)

        openings_by_wall_id.setdefault(int(host.id()), []).append(
            {
                "name": entity_name(door, f"Door {door.id()}"),
                "door_global_id": global_id(door),
                "door_entity_id": int(door.id()),
                "opening_global_id": global_id(opening),
                "opening_entity_id": int(opening.id()),
                "center": center,
                "width": width,
                "polygon": opening_poly,
                "z_min": door_z[0],
                "z_max": door_z[1],
            }
        )

    # ---------------------------------------------------------
    # Wall openings without a door (IfcOpeningElement with no fill)
    # Never opened automatically: the engineer includes the opening by its
    # GlobalId. Openings that look walkable are reported for review.
    # ---------------------------------------------------------
    filled_ids = _filled_opening_ids(model)
    opening_candidates: list[dict[str, Any]] = []
    unfilled_applied = 0

    for rel in model.by_type("IfcRelVoidsElement"):
        host = getattr(rel, "RelatingBuildingElement", None)
        opening = getattr(rel, "RelatedOpeningElement", None)
        if host is None or opening is None or not is_a(host, "IfcWall"):
            continue
        if int(opening.id()) in filled_ids:
            continue
        if effective_status(host, selection_overrides) != "include":
            continue

        opening_guid = global_id(opening)
        decision = selection_overrides.get(opening_guid) if opening_guid else None
        host_mesh = mesh_by_id.get(int(host.id()))
        shape = _opening_shape(model, opening)
        if shape is None or host_mesh is None:
            warnings.append(
                f"Wall opening {opening_guid or opening.id()} without a door has no usable geometry; it stays closed."
            )
            continue

        opening_poly, z_min, z_max = shape
        wall_min, _ = mesh_bounds(host_mesh)
        open_axis = axis_from_footprint(opening_poly)
        width = float(open_axis["length"])
        height = float(z_max - z_min)
        sill = float(z_min - wall_min[2])
        classification = classify_unfilled_opening(width, height, sill)
        applied = decision == "include"

        opening_candidates.append({
            "global_id": opening_guid,
            "name": entity_name(opening, ""),
            "host_wall_global_id": global_id(host),
            "host_wall_name": entity_name(host, ""),
            "level_key": resolve_level_key(host),
            "width": round(width, 3),
            "height": round(height, 3),
            "sill": round(sill, 3),
            "classification": classification,
            "decision": decision or "auto",
            "applied": applied,
        })

        if applied:
            unfilled_applied += 1
            openings_by_wall_id.setdefault(int(host.id()), []).append(
                {
                    "name": entity_name(opening, f"Opening {opening.id()}"),
                    "door_global_id": None,
                    "door_entity_id": None,
                    "opening_global_id": opening_guid,
                    "opening_entity_id": int(opening.id()),
                    "center": [float(opening_poly.centroid.x), float(opening_poly.centroid.y)],
                    "width": width,
                    "polygon": opening_poly,
                    "unfilled": True,
                    "z_min": z_min,
                    "z_max": z_max,
                }
            )

    pending_passages = [
        c for c in opening_candidates
        if c["classification"] == "passage_candidate" and c["decision"] == "auto"
    ]
    if pending_passages:
        warnings.append(
            f"{len(pending_passages)} wall opening(s) without a door look walkable (sill <= {PASSAGE_MAX_SILL:.2f} m, "
            f"height >= {PASSAGE_MIN_HEIGHT:.2f} m, width >= {PASSAGE_MIN_WIDTH:.2f} m) but are kept closed. "
            "Review them under Opening candidates and include the ones that are real passages."
        )

    # ---------------------------------------------------------
    # Walkable surfaces from selected floor slabs
    # v0.4.1 consolidates many structural slab panels per storey before
    # creating Viswalk Areas. Interior rings become generated low-height
    # obstacles because Vissim Areas cannot contain enclaves/holes.
    # ---------------------------------------------------------
    areas: list[dict[str, Any]] = []
    area_key = 1001
    walkable_components_by_level: dict[int, list[Polygon]] = defaultdict(list)
    walkable_source_ids_by_level: dict[int, list[int]] = defaultdict(list)
    walkable_source_guids_by_level: dict[int, list[str]] = defaultdict(list)
    walkable_source_slab_count = 0

    # Pass 1: collect every included slab with its footprint and walking height.
    slab_candidates: list[dict[str, Any]] = []

    for slab in model.by_type("IfcSlab"):
        guid = global_id(slab)
        manual = selection_overrides.get(guid) if guid else None
        status = effective_status(slab, selection_overrides)
        predefined = str(getattr(slab, "PredefinedType", "") or "").upper()
        is_roof_child = int(slab.id()) in roof_children

        if manual is None and is_roof_child:
            status = "exclude"
        elif manual is None and predefined not in {"FLOOR", "LANDING"}:
            # BASESLAB is intentionally review-only by default in Large Model Mode.
            status = "review"

        if status != "include":
            excluded_detail.append({
                "global_id": guid,
                "ifc_type": str(slab.is_a()),
                "reason": f"slab type {predefined or 'UNDEFINED'} or selection status",
            })
            continue

        mesh = mesh_by_id.get(int(slab.id()))
        if mesh is None:
            warnings.append(f"Included slab {guid or slab.id()} has no cached mesh.")
            continue

        footprint_geom = mesh_footprint(mesh.get("vertices", []), mesh.get("indices", []))
        components = polygon_components(footprint_geom)
        if not components:
            warnings.append(f"Included slab {guid or slab.id()} produced no valid 2D footprint.")
            continue

        level_key = resolve_level_key(slab)
        if level_key is None:
            warnings.append(f"Slab {guid or slab.id()} is not assigned to a building storey.")
            continue

        parent = parent_lookup.get(int(slab.id()))
        is_landing = predefined == "LANDING" or (
            parent is not None and (is_a(parent, "IfcStair") or is_a(parent, "IfcRamp"))
        )
        _, bbmax = mesh_bounds(mesh)
        slab_candidates.append({
            "slab": slab,
            "guid": guid,
            "level_key": level_key,
            "components": components,
            "top_z": float(bbmax[2]),
            "is_landing": is_landing,
        })

    # Walking datum per storey: footprint-area-weighted median top of included
    # non-landing slabs. Weighting by area keeps many small FLOOR-typed pieces
    # (sunscreens, louvres, sunken wet areas) from outvoting the main floor plate.
    # Storey Elevation stays the output level z (regression-stable); the datum
    # is used to classify landings and to snap stair ends.
    floor_tops_by_level: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for cand in slab_candidates:
        if not cand["is_landing"]:
            area = sum(c.area for c in cand["components"])
            floor_tops_by_level[cand["level_key"]].append((cand["top_z"], area))

    level_datum_by_key: dict[int, float] = {}
    for level in levels:
        key = int(level["key"])
        tops = sorted(floor_tops_by_level.get(key, []))
        if tops:
            datum = area_weighted_median(tops)
            shift = datum - level_z_by_key[key]
            if abs(shift) > STOREY_DATUM_WARNING:
                warnings.append(
                    f"Level {key} ({level['name']}): IfcBuildingStorey elevation {level_z_by_key[key]:.3f} m "
                    f"differs from floor-slab tops ({datum:.3f} m) by {shift:+.3f} m. Objects use the storey elevation; verify heights."
                )
        else:
            datum = level_z_by_key[key]
        level_datum_by_key[key] = datum

    # Pass 2: route storey floors vs. intermediate landings vs. off-level slabs.
    intermediate_landings: list[dict[str, Any]] = []
    off_level_slabs: list[dict[str, Any]] = []
    flattened_steps: list[dict[str, Any]] = []
    for cand in slab_candidates:
        level_key = cand["level_key"]
        datum = level_datum_by_key[level_key]
        if cand["is_landing"] and is_intermediate_landing(cand["top_z"], datum):
            intermediate_landings.append(cand)
            continue
        offset = cand["top_z"] - datum
        if not cand["is_landing"] and abs(offset) > INTERMEDIATE_LANDING_THRESHOLD:
            explicit = bool(cand["guid"]) and selection_overrides.get(cand["guid"]) == "include"
            area = round(sum(c.area for c in cand["components"]), 3)
            if abs(offset) > OFF_LEVEL_MERGE_MAX and not explicit:
                # Too far from the floor to be a step or a sunken finish (e.g. sunscreens,
                # canopies, mezzanines): not walkable until the engineer includes it.
                off_level_slabs.append({
                    "global_id": cand["guid"], "level_key": level_key, "top_z": round(cand["top_z"], 3),
                    "offset_m": round(offset, 3), "area_m2": area,
                    "name": entity_name(cand["slab"], f"IFC Slab {cand['slab'].id()}"), "decision": "auto",
                })
                warnings.append(
                    f"Floor slab {cand['guid'] or cand['slab'].id()} top ({cand['top_z']:.3f} m) is "
                    f"{offset:+.3f} m from its storey floor; left out of level {level_key} (not walkable until included in review)."
                )
                continue
            if explicit and abs(offset) > OFF_LEVEL_MERGE_MAX:
                # Included by the engineer: a mezzanine / raised floor gets a level of
                # its own at its real height (like an intermediate landing) instead of
                # being flattened onto the storey floor.
                off_level_slabs.append({
                    "global_id": cand["guid"], "level_key": level_key, "top_z": round(cand["top_z"], 3),
                    "offset_m": round(offset, 3), "area_m2": area,
                    "name": entity_name(cand["slab"], f"IFC Slab {cand['slab'].id()}"), "decision": "include",
                })
                cand["is_mezzanine"] = True
                intermediate_landings.append(cand)
                warnings.append(
                    f"Floor slab {cand['guid'] or cand['slab'].id()} top ({cand['top_z']:.3f} m) is "
                    f"{offset:+.3f} m from its storey floor; included as its own level (mezzanine). "
                    "Connect it with a stair/ramp or it will be unreachable."
                )
                continue
            warnings.append(
                f"Floor slab {cand['guid'] or cand['slab'].id()} top ({cand['top_z']:.3f} m) is "
                f"{offset:+.3f} m from its storey floor; merged into level {level_key}. Review whether it is a mezzanine or step."
            )
            # A real step people cannot walk over, flattened onto the floor (ENG-02).
            flattened_steps.append({"global_id": cand["guid"], "level_key": level_key,
                                    "offset_m": round(offset, 3), "area_m2": area})

        walkable_source_slab_count += 1
        walkable_components_by_level[level_key].extend(cand["components"])
        walkable_source_ids_by_level[level_key].append(int(cand["slab"].id()))
        if cand["guid"]:
            walkable_source_guids_by_level[level_key].append(cand["guid"])

    generated_void_masks: list[dict[str, Any]] = []
    walkable_region_count = 0
    walkable_void_count = 0
    ignored_void_count = 0

    for level_key in sorted(walkable_components_by_level):
        source_components = walkable_components_by_level[level_key]
        gap_stats: dict[str, int] = {}
        merged_regions = merge_walkable_components(source_components, grid_size=0.005, stats=gap_stats)
        if gap_stats.get("gaps_closed"):
            warnings.append(
                f"Level {level_key}: closed {gap_stats['gaps_closed']} gap(s) narrower than {WALKABLE_GAP_CLOSE * 1000:.0f} mm "
                "between floor slabs so the walking ground is continuous (Viswalk only connects touching/overlapping areas)."
            )

        if not merged_regions:
            warnings.append(
                f"Level {level_key}: {len(source_components)} floor component(s) could not be consolidated."
            )
            continue

        level_name = level_name_by_key.get(level_key, f"Level {level_key}")
        total_regions = len(merged_regions)

        for region_no, region in enumerate(merged_regions, start=1):
            if region.area <= EPS:
                continue

            name = f"Merged Walkable - {level_name}"
            if total_regions > 1:
                name += f" [region {region_no}/{total_regions}]"

            areas.append({
                "key": area_key,
                "name": name,
                "level_key": level_key,
                "polygon": polygon_points(region),
                "ifc_source_entity_ids": walkable_source_ids_by_level[level_key],
                "ifc_source_global_ids": walkable_source_guids_by_level[level_key],
                "consolidated_from_slabs": len(walkable_source_ids_by_level[level_key]),
            })
            area_key += 1
            walkable_region_count += 1

            holes = hole_polygons(region)
            small = [h for h in holes if h.area < MIN_VOID_MASK_AREA]
            ignored_void_count += len(small)
            holes = [h for h in holes if h.area >= MIN_VOID_MASK_AREA]
            for hole_no, hole in enumerate(holes, start=1):
                generated_void_masks.append({
                    "name": f"Walkable Void - {level_name} [{region_no}.{hole_no}]",
                    "type": "walkable_void_mask",
                    "level_key": level_key,
                    "height": 0.05,
                    "z_offset": 0.0,
                    "polygon": polygon_points(hole),
                    "generated": True,
                    "generated_from": "slab_union_interior_ring",
                })
                walkable_void_count += 1

    if ignored_void_count:
        warnings.append(
            f"{ignored_void_count} interior gap(s) smaller than {MIN_VOID_MASK_AREA:.2f} m2 in merged floor regions "
            "were treated as slab-joint gaps (no void mask)."
        )

    # ---------------------------------------------------------
    # Intermediate landings -> generated levels + areas
    # A landing between storeys cannot share the storey's walkable area: it
    # sits at a different height. Each landing height becomes a generated
    # level (keys 901+) so stair flights can connect level -> landing -> level.
    # ---------------------------------------------------------
    landing_levels = cluster_landing_levels(
        [c["top_z"] for c in intermediate_landings],
        [{"key": k, "z": z} for k, z in level_datum_by_key.items()],
        key_start=max(LANDING_LEVEL_KEY_START, len(levels) + 1),
    )
    landing_area_count = 0
    for landing_level in landing_levels:
        members = [
            c for c in intermediate_landings
            if abs(c["top_z"] - float(landing_level["z"])) <= LEVEL_SNAP_TOLERANCE
        ]
        if members and all(m.get("is_mezzanine") for m in members):
            landing_level["name"] = landing_level["name"].replace("Landing", "Mezzanine", 1)
        # Express the landing in the same frame as its storey's output level.
        base_key = members[0]["level_key"]
        shift = level_datum_by_key[base_key] - level_z_by_key[base_key]
        landing_level["match_z"] = landing_level["z"]
        landing_level["z"] = round(float(landing_level["z"]) - shift, 6)
        landing_level["source_storey_level_key"] = base_key

        components: list[Polygon] = []
        for member in members:
            components.extend(member["components"])
        regions = merge_walkable_components(components, grid_size=0.005)
        if not regions:
            warnings.append(
                f"{landing_level['name']}: {len(members)} landing slab(s) could not be consolidated."
            )
            continue
        for region_no, region in enumerate(regions, start=1):
            name = f"{'Mezzanine' if all(m.get('is_mezzanine') for m in members) else 'Landing'} - {landing_level['name']}"
            if len(regions) > 1:
                name += f" [region {region_no}/{len(regions)}]"
            if region.interiors:
                warnings.append(f"{name} has interior holes; only the outer boundary is used.")
            areas.append({
                "key": area_key,
                "name": name,
                "level_key": int(landing_level["key"]),
                "polygon": polygon_points(region),
                "ifc_source_entity_ids": [int(m["slab"].id()) for m in members],
                "ifc_source_global_ids": [m["guid"] for m in members if m["guid"]],
                "consolidated_from_slabs": len(members),
                "generated_level": True,
            })
            area_key += 1
            landing_area_count += 1
        walkable_source_slab_count += len(members)

    levels.extend(
        {k: v for k, v in lv.items() if k != "match_z"} for lv in landing_levels
    )

    # ---------------------------------------------------------
    # Physical wall segments (door openings split here)
    # ---------------------------------------------------------
    walls: list[dict[str, Any]] = []
    polygon_wall_obstacles: list[dict[str, Any]] = []
    polygon_wall_count = 0
    logical_wall_count = 0
    wall_key = 1101
    storey_z = sorted((level_z_by_key[int(lv["key"])], int(lv["key"]))
                      for lv in levels if not lv.get("generated") and int(lv["key"]) in level_z_by_key)

    for wall in model.by_type("IfcWall"):
        if effective_status(wall, selection_overrides) != "include":
            continue
        mesh = mesh_by_id.get(int(wall.id()))
        if mesh is None:
            warnings.append(f"Included wall {global_id(wall) or wall.id()} has no cached mesh.")
            continue

        footprint = largest_polygon(mesh_footprint(mesh.get("vertices", []), mesh.get("indices", [])))
        if footprint is None or footprint.area <= EPS:
            warnings.append(f"Included wall {global_id(wall) or wall.id()} produced no footprint.")
            continue

        axis = axis_from_footprint(footprint)
        bbmin, bbmax = mesh_bounds(mesh)
        height = max(bbmax[2] - bbmin[2], 0.05)
        level_key = resolve_level_key(wall)
        if level_key is None:
            warnings.append(f"Wall {global_id(wall) or wall.id()} has no storey; skipped.")
            continue
        z_offset = bbmin[2] - level_z_by_key[level_key]
        if abs(z_offset) < 1e-5:
            z_offset = 0.0

        logical_wall_count += 1
        all_openings = openings_by_wall_id.get(int(wall.id()), [])

        # A wall modelled once over several storeys is exported per storey, each
        # storey cut only by the openings at its own walking height (a ground-floor
        # door must not open the wall upstairs).
        bands = wall_storey_bands(bbmin[2], bbmax[2], level_key, storey_z)
        for band_no, (band_level, band_bottom, band_top) in enumerate(bands):
            if len(bands) == 1:
                wall_openings = all_openings
                band_suffix = ""
            else:
                floor_z = level_z_by_key[band_level]
                wall_openings = [o for o in all_openings if opening_at_walking_height(o, floor_z, band_no == 0)]
                band_suffix = "" if band_no == 0 else f" [continues on {level_name_by_key.get(band_level, band_level)}]"
            level_key = band_level
            height = max(band_top - band_bottom, 0.05)
            z_offset = band_bottom - level_z_by_key[band_level]
            if abs(z_offset) < 1e-5:
                z_offset = 0.0

            solidity = wall_footprint_solidity(footprint)
            if solidity < WALL_POLYGON_SOLIDITY:
                # L/T/curved wall: a single centreline would block the corner.
                # Keep the true footprint and cut openings out of it.
                cut = [o["polygon"].buffer(0.001) for o in wall_openings if o.get("polygon") is not None]
                missing = [o for o in wall_openings if o.get("polygon") is None]
                if missing:
                    warnings.append(
                        f"Wall {global_id(wall) or wall.id()} is not straight and {len(missing)} of its openings have no footprint; those openings stay closed."
                    )
                geom = footprint.difference(unary_union(cut)) if cut else footprint
                parts = [
                    piece
                    for comp in polygon_components(geom if geom.is_valid else geom.buffer(0))
                    for piece in split_out_holes(comp)
                ]
                door_openings_applied += len({o["door_global_id"] for o in wall_openings if o.get("door_global_id") and o.get("polygon") is not None})
                name = entity_name(wall, f"IFC Wall {wall.id()}")
                for part_no, part in enumerate(parts, start=1):
                    polygon_wall_obstacles.append({
                        "name": (name if len(parts) == 1 else f"{name} [part {part_no}/{len(parts)}]") + band_suffix,
                        "storey_split": len(bands) > 1,
                        **({"replicated_from_level": bands[0][0]} if band_no else {}),
                        "type": "IfcWall",
                        "level_key": level_key,
                        "height": round(height, 5),
                        "z_offset": round(z_offset, 5),
                        "polygon": polygon_points(part),
                        "ifc_global_id": global_id(wall),
                        "ifc_entity_id": int(wall.id()),
                        "logical_wall_global_id": global_id(wall),
                        "wall_shape": "polygon",
                        "footprint_solidity": round(solidity, 4),
                    })
                if band_no == 0:
                    polygon_wall_count += 1
                continue

            physical_segments, normalized_openings = split_wall_axis(
                axis["start"], axis["end"], wall_openings
            )

            # Sanity-check opening centers against the inferred wall axis.
            valid_opening_guids = set()
            for opening_info in normalized_openings:
                label = opening_info.get("door_global_id") or opening_info.get("opening_global_id")
                if opening_info["perpendicular_distance"] > max(axis["thickness"] * 1.5, 0.35):
                    warnings.append(
                        f"{'Door' if opening_info.get('door_global_id') else 'Opening'} {label} is {opening_info['perpendicular_distance']:.3f} m from inferred wall axis; verify this opening in 3D review."
                    )
                valid_opening_guids.add(opening_info.get("door_global_id"))
            door_openings_applied += len([g for g in valid_opening_guids if g])

            if not physical_segments:
                warnings.append(
                    f"Wall {global_id(wall) or wall.id()} has no remaining physical segment after door splitting."
                )
                continue

            total_parts = len(physical_segments)
            for part_no, seg in enumerate(physical_segments, start=1):
                name = entity_name(wall, f"IFC Wall {wall.id()}")
                if total_parts > 1:
                    name = f"{name} [segment {part_no}/{total_parts}]"
                name += band_suffix

                walls.append(
                    {
                        "key": wall_key,
                        "name": name,
                        "level_key": level_key,
                        "start": [round(seg["start"][0], 5), round(seg["start"][1], 5)],
                        "end": [round(seg["end"][0], 5), round(seg["end"][1], 5)],
                        "thickness": round(axis["thickness"], 5),
                        "height": round(height, 5),
                        "z_offset": round(z_offset, 5),
                        "ifc_global_id": global_id(wall),
                        "ifc_entity_id": int(wall.id()),
                        "logical_wall_global_id": global_id(wall),
                        "physical_segment": True,
                        "storey_split": len(bands) > 1,
                        **({"replicated_from_level": bands[0][0]} if band_no else {}),
                    }
                )
                wall_key += 1

    # ---------------------------------------------------------
    # Columns and generic movement obstacles
    # ---------------------------------------------------------
    columns: list[dict[str, Any]] = []
    obstacles: list[dict[str, Any]] = []
    plates_off_walking_height = 0
    column_key = 1301
    obstacle_key = 1401

    for generated in generated_void_masks:
        obstacles.append({"key": obstacle_key, **generated})
        obstacle_key += 1

    for wall_obstacle in polygon_wall_obstacles:
        obstacles.append({"key": obstacle_key, **wall_obstacle})
        obstacle_key += 1

    for element in model.by_type("IfcElement"):
        if is_a(element, "IfcWall") or is_a(element, "IfcDoor") or is_a(element, "IfcWindow") or is_a(element, "IfcSlab"):
            continue
        if is_a(element, "IfcFeatureElement"):
            # Openings/projections are handled through their host element;
            # an included opening GlobalId is a wall-split decision.
            continue
        if is_a(element, "IfcStair") or is_a(element, "IfcStairFlight") or is_a(element, "IfcRamp") or is_a(element, "IfcRampFlight"):
            continue

        if effective_status(element, selection_overrides) != "include":
            continue

        label = f"{element.is_a()} {global_id(element) or element.id()}"
        rec, _, role = recommendation(element)
        if role not in {"obstacle", "review"} and not is_a(element, "IfcColumn"):
            warnings.append(
                f"Included {label} has simulation role '{role}', which has no semantic mapping; not exported."
            )
            continue

        mesh = mesh_by_id.get(int(element.id()))
        if mesh is None:
            warnings.append(f"Included {label} has no cached mesh; not exported.")
            continue
        footprint = largest_polygon(mesh_footprint(mesh.get("vertices", []), mesh.get("indices", [])))
        if footprint is None or footprint.area <= EPS:
            warnings.append(f"Included {label} produced no 2D footprint; not exported.")
            continue
        bbmin, bbmax = mesh_bounds(mesh)
        height = max(bbmax[2] - bbmin[2], 0.05)
        level_key = resolve_level_key(element)
        if level_key is None:
            warnings.append(f"Included {label} is not assigned to a building storey; not exported.")
            continue
        z_offset = bbmin[2] - level_z_by_key[level_key]
        if abs(z_offset) < 1e-5:
            z_offset = 0.0
        if (is_a(element, "IfcPlate") or is_a(element, "IfcMember")) and (
                bbmax[2] - level_z_by_key[level_key] < PLATE_MIN_TOP or z_offset > PLATE_MAX_BOTTOM):
            plates_off_walking_height += 1
            continue

        if is_a(element, "IfcColumn"):
            compactness = 0.0
            if footprint.length > EPS:
                compactness = 4.0 * math.pi * footprint.area / (footprint.length ** 2)

            if compactness > 0.86 and len(footprint.exterior.coords) >= 10:
                diameter = 2.0 * math.sqrt(footprint.area / math.pi)
                columns.append(
                    {
                        "key": column_key,
                        "name": entity_name(element, f"IFC Column {element.id()}"),
                        "level_key": level_key,
                        "shape": "circle",
                        "center": [round(footprint.centroid.x, 5), round(footprint.centroid.y, 5)],
                        "diameter": round(diameter, 5),
                        "height": round(height, 5),
                        "z_offset": round(z_offset, 5),
                        "ifc_global_id": global_id(element),
                        "ifc_entity_id": int(element.id()),
                    }
                )
            else:
                axis = axis_from_footprint(footprint)
                rect = axis["rectangle"]
                rect_coords = list(rect.exterior.coords)[:-1]
                edge_a = math.dist(rect_coords[0], rect_coords[1])
                edge_b = math.dist(rect_coords[1], rect_coords[2])
                columns.append(
                    {
                        "key": column_key,
                        "name": entity_name(element, f"IFC Column {element.id()}"),
                        "level_key": level_key,
                        "shape": "rectangle",
                        "center": [round(footprint.centroid.x, 5), round(footprint.centroid.y, 5)],
                        "width": round(edge_a, 5),
                        "depth": round(edge_b, 5),
                        "rotation_deg": round(axis["rotation_deg"], 5),
                        "height": round(height, 5),
                        "z_offset": round(z_offset, 5),
                        "ifc_global_id": global_id(element),
                        "ifc_entity_id": int(element.id()),
                    }
                )
            column_key += 1
        else:
            obstacles.append(
                {
                    "key": obstacle_key,
                    "name": entity_name(element, f"IFC Obstacle {element.id()}"),
                    "type": str(element.is_a()),
                    "level_key": level_key,
                    "height": round(height, 5),
                    "z_offset": round(z_offset, 5),
                    "polygon": polygon_points(footprint),
                    "ifc_global_id": global_id(element),
                    "ifc_entity_id": int(element.id()),
                }
            )
            obstacle_key += 1
    if plates_off_walking_height:
        warnings.append(
            f"{plates_off_walking_height} IfcPlate/IfcMember element(s) not at walking height "
            f"(top below {PLATE_MIN_TOP:.2f} m or bottom above {PLATE_MAX_BOTTOM:.2f} m over their level); not exported as obstacles."
        )

    # ---------------------------------------------------------
    # Vertical connections (geometry-aware, one record per flight)
    # ---------------------------------------------------------
    match_levels = [
        {"key": int(level["key"]), "z": level_datum_by_key.get(int(level["key"]), float(level["z"]))}
        for level in levels
        if not level.get("generated")
    ] + [
        {"key": int(lv["key"]), "z": float(lv["match_z"]), "generated": True} for lv in landing_levels
    ]

    def _included(entity: Any) -> bool:
        return effective_status(entity, selection_overrides) == "include"

    def _explicitly_excluded(entity: Any) -> bool:
        guid = global_id(entity)
        return bool(guid) and selection_overrides.get(guid) == "exclude"

    vertical_units, unit_warnings = collect_vertical_units(
        model,
        is_included=_included,
        is_explicitly_excluded=_explicitly_excluded,
        children_of=children_map(model),
        parent_of=parent_lookup,
        has_mesh=lambda e: int(e.id()) in mesh_by_id,
    )
    warnings.extend(unit_warnings)

    vertical_connections, vertical_warnings = build_vertical_connections(
        vertical_units,
        mesh_for=lambda e: mesh_by_id.get(int(e.id())),
        footprint_for=lambda m: largest_polygon(mesh_footprint(m.get("vertices", []), m.get("indices", []))),
        all_levels=match_levels,
    )
    warnings.extend(vertical_warnings)
    trim_ramp_end_overlaps(vertical_connections, areas, obstacles)

    for element in model.by_type("IfcTransportElement"):
        if _included(element):
            warnings.append(
                f"IfcTransportElement {global_id(element) or element.id()} (elevator/escalator) is included; "
                "it is exported only as an obstacle footprint. Model the elevator in Viswalk manually."
            )

    storey_levels = [lv for lv in levels if not lv.get("generated")]
    multi_replicated, multi_copies, multi_closed = replicate_across_storeys(
        walls, columns, obstacles, storey_levels, level_z_by_key)
    # Walls already exported per storey (with openings at each storey's height).
    split_walls = [w for w in walls + obstacles if w.get("storey_split")]
    multi_replicated += len({w.get("logical_wall_global_id") or w.get("ifc_global_id") for w in split_walls})
    multi_copies += sum(1 for w in split_walls if w.get("replicated_from_level"))
    if multi_replicated:
        warnings.append(
            f"{multi_replicated} wall/column/obstacle element(s) span several storeys; copied onto each storey "
            f"they cross ({multi_copies} copies) because Vissim obstacles act only on their own level. "
            "Walls are cut on each storey only by the openings at that storey's walking height."
        )
    if multi_closed:
        warnings.append(
            f"{multi_closed} multi-storey wall copies are exported without door gaps on the upper storeys "
            "(the lower storey's doors do not carry up). Review doors on those storeys."
        )
        diag("multi_storey_no_doors", [], count=int(multi_closed))

    # Engineer's manual plan edits (added floor / obstacles / passages).
    from manual_edits import apply_manual_edits
    manual_status: dict[str, dict[str, Any]] = {}
    manual_applied = apply_manual_edits(
        manual_edits or [], areas=areas, walls=walls, obstacles=obstacles,
        level_z={int(lv["key"]): float(lv["z"]) for lv in levels}, warnings=warnings,
        status=manual_status,
    )
    if any(manual_applied[k] for k in ("walkable", "obstacle", "passage")):
        warnings.append(
            f"Manual plan edits applied: {manual_applied['walkable']} walkable, {manual_applied['obstacle']} obstacle, "
            f"{manual_applied['passage']} passage (engineer-drawn, not from the IFC)."
        )

    key_ranges = assign_key_ranges({
        "areas": areas,
        "walls": walls,
        "columns": columns,
        "obstacles": obstacles,
        "vertical_connections": vertical_connections,
    })

    # Pedestrian connectivity (graph of free walking space + stairs). Diagnostic only.
    from connectivity_service import analyze_connectivity, connectivity_warnings
    try:
        connectivity = analyze_connectivity({
            "levels": levels + [lv for lv in landing_levels],
            "areas": areas, "walls": walls, "columns": columns, "obstacles": obstacles,
            "vertical_connections": vertical_connections,
        })
        warnings.extend(connectivity_warnings(connectivity))
    except Exception as exc:  # noqa: BLE001 - never block conversion on a diagnostic
        connectivity = {"error": f"{type(exc).__name__}: {exc}"}

    # ---------------------------------------------------------
    # Summary / audit metadata
    # ---------------------------------------------------------
    source_door_count = len(model.by_type("IfcDoor"))
    source_window_count = len(model.by_type("IfcWindow"))

    summary = {
        "levels": len([lv for lv in levels if not lv.get("generated")]),
        "walkable_source_slabs": walkable_source_slab_count,
        "walkable_areas": len(areas),
        "walkable_regions": walkable_region_count,
        "walkable_void_masks": walkable_void_count,
        "ignored_tiny_voids": ignored_void_count,
        "logical_walls": logical_wall_count,
        "physical_wall_segments": len(walls),
        "included_doors": included_door_count,
        "door_openings_applied": door_openings_applied,
        "unfilled_openings": len(opening_candidates),
        "unfilled_passage_candidates": sum(1 for c in opening_candidates if c["classification"] == "passage_candidate"),
        "unfilled_openings_applied": unfilled_applied,
        "polygon_walls": polygon_wall_count,
        "windows_used_as_openings": 0,
        "source_windows": source_window_count,
        "columns": len(columns),
        "obstacles": len(obstacles),
        "vertical_connections": len(vertical_connections),
        "vertical_ends_with_offset": sum(
            1 for v in vertical_connections for end in ("start", "end")
            if v["level_match"][end] != "exact"
        ),
        "generated_landing_levels": len(landing_levels),
        "off_level_slabs": len(off_level_slabs),
        "off_level_slabs_excluded": sum(1 for x in off_level_slabs if x["decision"] != "include"),
        "isolated_zones": len(connectivity.get("isolated_zones", [])) if isinstance(connectivity, dict) else 0,
        "stairs_not_linked": len(connectivity.get("stairs_not_linked", [])) if isinstance(connectivity, dict) else 0,
        "multi_storey_elements": multi_replicated,
        "multi_storey_copies": multi_copies,
        "landing_areas": landing_area_count,
        "warnings": len(warnings),
    }

    project = next(iter(model.by_type("IfcProject")), None)

    return {
        "project": {
            "name": entity_name(project, path.stem) if project is not None else path.stem,
            "units": "m",
            "source": "IFC",
            "source_file": path.name,
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
        "levels": levels,
        "areas": areas,
        "walls": walls,
        "columns": columns,
        "obstacles": obstacles,
        "vertical_connections": vertical_connections,
        "ifc_semantic": {
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "engine_contract": ENGINE_CONTRACT,
            "ifc_schema": str(model.schema),
            "unit_scale_to_m": unit_scale,
            "key_ranges": key_ranges,
            "selection_overrides": selection_overrides,
            "summary": summary,
            "warnings": warnings,
            "excluded_detail_preview": excluded_detail[:100],
            # Full list: the Viswalk checklist is built from it. The UI pages it.
            "opening_candidates": opening_candidates,
            "off_level_slabs": off_level_slabs,
            "flattened_steps": flattened_steps,
            "diagnostics": diagnostics,
            "connectivity": connectivity,
            "manual_edits": list(manual_edits or []),
            "manual_edits_applied": manual_applied,
            "manual_edits_status": manual_status,
            "door_logic": {
                "source_doors": source_door_count,
                "included_doors": included_door_count,
                "door_openings_applied": door_openings_applied,
                "source_windows": source_window_count,
                "windows_used_as_openings": 0,
            },
            "notes": [
                "Walls in this file are physical segments; there is no hidden openings metadata in engine-facing wall records.",
                "Only included IfcDoor relationships split walls automatically. IfcWindow never creates a pedestrian opening. Unfilled IfcOpeningElements split a wall only when the engineer includes the opening GlobalId; walkable-looking ones are listed in opening_candidates.",
                "Walls whose footprint is not convex (L/T/curved) are exported as polygon obstacles with openings cut out, instead of a single centreline wall.",
                "Roof/base/non-floor slabs are not promoted automatically unless their IFC rule or manual selection includes them.",
                "IfcSlab floor panels are consolidated per storey before creating Viswalk Areas.",
                "Interior holes in consolidated floor regions become generated walkable-void obstacles because Vissim Areas cannot contain enclaves.",
                "Stairs/ramps are converted one record per flight from mesh geometry; polygon order is bottom edge first. Ends snap to storey or generated landing levels within the snap tolerance, otherwise an explicit z offset and a warning are emitted.",
                "Intermediate landing slabs become generated levels (keys 901+) with their own areas instead of being merged into the storey floor.",
            ],
        },
    }


def write_semantic_model(path: Path, model: dict[str, Any]) -> None:
    import os
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(
        json.dumps(model, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)          # readers never see a half-written model
