"""Pedestrian connectivity diagnostic on the semantic model - geometry only (P1-04).

This is a pre-flight diagnostic, not routing verification: it does not know
origins, exits, clear widths or Viswalk's route choice. "Connected" here means
the free walking space touches; it does not mean every person can reach an exit.

Geometry can be valid while people still cannot get anywhere: a room whose door
was not converted, a floor reached by no stair. This builds a graph:

* node  = a connected piece of free walking space on one level
          (walkable areas of the level minus wall/column/obstacle footprints)
* edge  = a stair/ramp whose bottom end touches one node and top end another

and reports every zone that cannot be reached from the largest network. It runs
on the semantic model alone (no Vissim) and never changes the model.
"""
from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

# Free-space pieces smaller than this are slivers between touching obstacles.
MIN_ZONE_AREA = 1.0
# Obstacles starting this high above their level do not block walking.
HEADROOM_CLEAR = 2.0
# Tolerance when testing whether a stair end touches walking space.
END_TOUCH = 0.15


def _poly(points: list[list[float]] | None) -> Polygon | None:
    if not points or len(points) < 3:
        return None
    p = Polygon(points)
    return p if p.is_valid else p.buffer(0)


def _footprint(rec: dict[str, Any]) -> Any:
    if rec.get("polygon"):
        return _poly(rec["polygon"])
    if rec.get("start") and rec.get("end"):
        return LineString([rec["start"], rec["end"]]).buffer(float(rec.get("thickness") or 0.1) / 2, cap_style=2)
    if rec.get("center"):
        cx, cy = rec["center"]
        if rec.get("shape") == "circle":
            return Point(cx, cy).buffer(float(rec.get("diameter") or 0.3) / 2)
        w, d = float(rec.get("width") or 0.3), float(rec.get("depth") or 0.3)
        a = math.radians(float(rec.get("rotation_deg") or 0.0))
        ux, uy, vx, vy = math.cos(a) * w / 2, math.sin(a) * w / 2, -math.sin(a) * d / 2, math.cos(a) * d / 2
        return Polygon([(cx - ux - vx, cy - uy - vy), (cx + ux - vx, cy + uy - vy),
                        (cx + ux + vx, cy + uy + vy), (cx - ux + vx, cy - uy + vy)])
    return None


def _ends(vc: dict[str, Any]) -> tuple[Any, Any]:
    if vc.get("bottom_edge") and vc.get("top_edge"):
        return LineString(vc["bottom_edge"]), LineString(vc["top_edge"])
    pts = vc.get("polygon") or []
    if len(pts) == 4:
        return LineString(pts[0:2]), LineString(pts[2:4])
    c = _poly(pts).centroid if pts else Point(0, 0)
    return c, c


def analyze_connectivity(model: dict[str, Any]) -> dict[str, Any]:
    levels = {int(l["key"]): l for l in model.get("levels", [])}
    blockers: dict[int, list[Any]] = {}
    for key in ("walls", "columns", "obstacles"):
        for rec in model.get(key, []):
            if rec.get("type") == "walkable_void_mask":
                geom = _footprint(rec)          # holes in the floor block like obstacles
            elif float(rec.get("z_offset") or 0.0) >= HEADROOM_CLEAR:
                continue
            else:
                geom = _footprint(rec)
            if geom is not None and not geom.is_empty:
                blockers.setdefault(int(rec["level_key"]), []).append(geom)

    nodes: list[dict[str, Any]] = []
    by_level: dict[int, list[int]] = {}
    for level_key in sorted({int(a["level_key"]) for a in model.get("areas", [])}):
        floor = unary_union([p for a in model["areas"] if int(a["level_key"]) == level_key
                             for p in [_poly(a.get("polygon"))] if p is not None])
        if blockers.get(level_key):
            floor = floor.difference(unary_union(blockers[level_key]))
        parts = list(getattr(floor, "geoms", [floor]))
        for part in parts:
            if part.is_empty or part.area < MIN_ZONE_AREA:
                continue
            by_level.setdefault(level_key, []).append(len(nodes))
            nodes.append({"level_key": level_key, "geom": part})

    parent = list(range(len(nodes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def touching(level_key: int, end: Any) -> list[int]:
        probe = end.buffer(END_TOUCH)
        return [i for i in by_level.get(level_key, []) if nodes[i]["geom"].intersects(probe)]

    stair_links = []
    dangling = []
    for vc in model.get("vertical_connections", []):
        bottom, top = _ends(vc)
        a = touching(int(vc["start_level"]), bottom)
        b = touching(int(vc["end_level"]), top)
        if not a or not b:
            dangling.append({"key": vc.get("key"), "ifc_global_id": vc.get("ifc_global_id"),
                             "start_level": vc["start_level"], "end_level": vc["end_level"],
                             "bottom_connected": bool(a), "top_connected": bool(b)})
            continue
        for i in a + b:
            parent[find(i)] = find(a[0])
        stair_links.append(vc.get("key"))

    groups: dict[int, list[int]] = {}
    for i in range(len(nodes)):
        groups.setdefault(find(i), []).append(i)
    ranked = sorted(groups.values(), key=lambda g: -sum(nodes[i]["geom"].area for i in g))
    main = ranked[0] if ranked else []
    isolated = []
    for group in ranked[1:]:
        for i in group:
            g = nodes[i]["geom"]
            isolated.append({
                "level_key": nodes[i]["level_key"],
                "level_name": levels.get(nodes[i]["level_key"], {}).get("name"),
                "area_m2": round(g.area, 2),
                "centroid": [round(g.centroid.x, 3), round(g.centroid.y, 3)],
                "polygon": [[round(x, 3), round(y, 3)] for x, y in list(g.exterior.coords)[:-1]],
            })
    isolated.sort(key=lambda z: -z["area_m2"])
    main_levels = sorted({nodes[i]["level_key"] for i in main})
    return {
        "zones": len(nodes),
        "networks": len(ranked),
        "main_network_area_m2": round(sum(nodes[i]["geom"].area for i in main), 2),
        "main_network_levels": main_levels,
        "isolated_zones": isolated,
        "isolated_area_m2": round(sum(z["area_m2"] for z in isolated), 2),
        "stairs_linked": len(stair_links),
        "stairs_not_linked": dangling,
        "min_zone_area_m2": MIN_ZONE_AREA,
    }


def connectivity_warnings(result: dict[str, Any]) -> list[str]:
    out = []
    iso = result["isolated_zones"]
    if iso:
        top = ", ".join(f"level {z['level_key']} {z['area_m2']:.1f} m2 at ({z['centroid'][0]:.1f}, {z['centroid'][1]:.1f})"
                        for z in iso[:5])
        out.append(
            f"Connectivity (geometry-only): {len(iso)} walking zone(s) ({result['isolated_area_m2']:.1f} m2) cannot be reached from the "
            f"main pedestrian network (levels {result['main_network_levels']}). Largest: {top}. "
            "Check for missing doors/openings or stairs."
        )
    for d in result["stairs_not_linked"]:
        side = "bottom" if not d["bottom_connected"] else "top"
        out.append(
            f"Connectivity (geometry-only): stair/ramp {d['ifc_global_id'] or d['key']} ({d['start_level']} -> {d['end_level']}) "
            f"{side} end does not reach free walking space (blocked by a wall/obstacle or no floor)."
        )
    return out
