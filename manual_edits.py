"""Engineer's manual fixes drawn on the 2D plan (P1-02).

Edits are stored in the project state, never in the IFC, and re-applied every
time the pedestrian model is generated:

* ``walkable`` - add walking floor (e.g. a floor the IFC lacks)
* ``obstacle`` - add a blocked zone (e.g. a counter, a closed room)
* ``passage``  - open a gap through walls (e.g. a door the IFC did not link)

Each edit is a polygon on one level (semantic level key, including landings and
mezzanines). They are applied after IFC conversion, so the model stays traceable:
every generated object carries ``manual_edit_id``.
"""
from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

EDIT_KINDS = ("walkable", "obstacle", "passage")
MANUAL_OBSTACLE_HEIGHT = 2.0


def _poly(points: list[list[float]]) -> Polygon:
    p = Polygon(points)
    return p if p.is_valid else p.buffer(0)


def _pts(geom: Polygon) -> list[list[float]]:
    return [[round(x, 5), round(y, 5)] for x, y in list(geom.exterior.coords)[:-1]]


def validate_edit(edit: dict[str, Any]) -> str | None:
    if edit.get("kind") not in EDIT_KINDS:
        return f"kind must be one of {EDIT_KINDS}"
    pts = edit.get("polygon") or []
    if len(pts) < 3:
        return "polygon needs at least 3 points"
    p = _poly(pts)
    if p.is_empty or p.area < 0.01:
        return "polygon area is too small"
    return None


def apply_manual_edits(edits: list[dict[str, Any]], *, areas: list[dict[str, Any]],
                       walls: list[dict[str, Any]], obstacles: list[dict[str, Any]],
                       level_keys: set[int], warnings: list[str]) -> dict[str, int]:
    applied = {"walkable": 0, "obstacle": 0, "passage": 0, "skipped": 0}
    for edit in edits or []:
        level = int(edit.get("level_key", -1))
        problem = validate_edit(edit)
        if problem or level not in level_keys:
            applied["skipped"] += 1
            warnings.append(f"Manual edit {edit.get('id')} skipped: {problem or f'level {level} not in model'}.")
            continue
        shape = _poly(edit["polygon"])
        kind = edit["kind"]
        tag = {"manual_edit_id": edit.get("id"), "generated": True}

        if kind == "walkable":
            # Added as drawn, overlapping the existing floor: Viswalk joins areas that
            # overlap, whereas a cut-to-fit piece would only touch along a seam.
            areas.append({"name": f"Manual walkable {edit.get('id')}", "level_key": level,
                          "polygon": _pts(shape), **tag})
            applied["walkable"] += 1

        elif kind == "obstacle":
            obstacles.append({"name": f"Manual obstacle {edit.get('id')}", "type": "manual_obstacle",
                              "level_key": level, "height": MANUAL_OBSTACLE_HEIGHT, "z_offset": 0.0,
                              "polygon": _pts(shape), **tag})
            applied["obstacle"] += 1

        elif kind == "passage":
            cut = 0
            for wall in [w for w in walls if int(w["level_key"]) == level]:
                line = LineString([wall["start"], wall["end"]])
                if not line.intersects(shape):
                    continue
                rest = line.difference(shape)
                walls.remove(wall)
                cut += 1
                for n, piece in enumerate(getattr(rest, "geoms", [rest]), start=1):
                    if piece.is_empty or piece.length < 0.02:
                        continue
                    coords = list(piece.coords)
                    walls.append({**wall, "start": [round(coords[0][0], 5), round(coords[0][1], 5)],
                                  "end": [round(coords[-1][0], 5), round(coords[-1][1], 5)],
                                  "name": f"{wall['name']} [cut by passage {edit.get('id')}]",
                                  "manual_edit_id": edit.get("id")})
            for obs in [o for o in obstacles if int(o["level_key"]) == level and o.get("type") == "IfcWall"
                        and o.get("polygon")]:
                geom = _poly(obs["polygon"])
                if not geom.intersects(shape):
                    continue
                rest = geom.difference(shape)
                obstacles.remove(obs)
                cut += 1
                for n, piece in enumerate(getattr(rest, "geoms", [rest]), start=1):
                    if isinstance(piece, Polygon) and piece.area > 0.001:
                        obstacles.append({**obs, "polygon": _pts(piece),
                                          "name": f"{obs['name']} [cut by passage {edit.get('id')}]",
                                          "manual_edit_id": edit.get("id")})
            if not cut:
                warnings.append(f"Manual passage {edit.get('id')} on level {level} crosses no wall.")
            applied["passage"] += 1
    return applied
