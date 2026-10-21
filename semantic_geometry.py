"""Polygon helpers for the pedestrian (semantic) model: footprints from meshes,
cleaning and merging walkable floor pieces, holes. Pure geometry, no IFC."""
from __future__ import annotations

import math
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union


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


def merge_walkable_components(components: list[Polygon], grid_size: float = 0.005,
                              close_gap: float = WALKABLE_GAP_CLOSE,
                              stats: dict[str, Any] | None = None) -> list[Polygon]:
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
                if stats is not None:
                    stats["gaps_closed"] = stats.get("gaps_closed", 0) + (before - after)
                    # Where the closing added floor (ENG-03): kept so the engineer can
                    # see every automatic repair on the plan.
                    added = closed.difference(merged)
                    stats.setdefault("repairs", []).extend(
                        piece for piece in polygon_components(added) if piece.area > 1e-5)
                merged = closed
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


def _farthest_pair(points: list[list[float]]) -> tuple[list[float], list[float]]:
    best = (points[0], points[-1])
    best_d = -1.0
    for i, a in enumerate(points):
        for b in points[i + 1:]:
            d = math.dist(a, b)
            if d > best_d:
                best, best_d = (a, b), d
    return best


EPS = 1e-8
