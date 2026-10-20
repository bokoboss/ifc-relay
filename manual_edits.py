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
    if len(pts) < 3 or len(pts) > 200:
        return "polygon needs 3 to 200 points"
    import math
    if not all(len(p) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) < 1e6 for v in p)
               for p in pts):
        return "polygon has invalid coordinates"
    if not Polygon(pts).is_valid:
        return "polygon is self-intersecting"
    p = _poly(pts)
    if p.is_empty or p.area < 0.01:
        return "polygon area is too small"
    return None


# A level is the same level when its height is within this tolerance.
LEVEL_REBIND_TOLERANCE = 0.15


def resolve_edit_level(edit: dict[str, Any], level_z: dict[int, float]) -> tuple[int | None, str]:
    """Level the edit belongs to in this model.

    Generated levels (landings 901+, mezzanines) are numbered per model, so a key
    saved for one IFC revision may mean another height in the next. An edit keeps
    the height it was drawn at (``level_z``) and is re-bound by height."""
    key = int(edit.get("level_key", -1))
    z = edit.get("level_z")
    if z is None:
        return (key, "") if key in level_z else (None, f"level {key} not in model")
    z = float(z)
    if key in level_z and abs(level_z[key] - z) <= LEVEL_REBIND_TOLERANCE:
        return key, ""
    close = sorted((abs(lz - z), k) for k, lz in level_z.items() if abs(lz - z) <= LEVEL_REBIND_TOLERANCE)
    if close:
        return close[0][1], f"re-bound from level {key} to level {close[0][1]} by height {z:.2f} m"
    return None, f"no level at {z:.2f} m (was level {key})"


def apply_manual_edits(edits: list[dict[str, Any]], *, areas: list[dict[str, Any]],
                       walls: list[dict[str, Any]], obstacles: list[dict[str, Any]],
                       level_z: dict[int, float], warnings: list[str],
                       status: dict[str, dict[str, Any]] | None = None) -> dict[str, int]:
    applied = {"walkable": 0, "obstacle": 0, "passage": 0, "skipped": 0}
    status = status if status is not None else {}
    for edit in edits or []:
        problem = validate_edit(edit)
        level, note = resolve_edit_level(edit, level_z)
        if problem or level is None:
            applied["skipped"] += 1
            status[str(edit.get("id"))] = {"applied": False, "reason": problem or note}
            warnings.append(f"Manual edit {edit.get('id')} skipped: {problem or note}.")
            continue
        status[str(edit.get("id"))] = {"applied": True, "level_key": level, "note": note}
        if note:
            warnings.append(f"Manual edit {edit.get('id')} {note}.")
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
                from ifc_semantic_service import split_out_holes
                pieces = [p for part in getattr(rest, "geoms", [rest]) if isinstance(part, Polygon)
                          for p in split_out_holes(part)]
                for n, piece in enumerate(pieces, start=1):
                    if isinstance(piece, Polygon) and piece.area > 0.001:
                        obstacles.append({**obs, "polygon": _pts(piece),
                                          "name": f"{obs['name']} [cut by passage {edit.get('id')}]",
                                          "manual_edit_id": edit.get("id")})
            if not cut:
                warnings.append(f"Manual passage {edit.get('id')} on level {level} crosses no wall.")
            applied["passage"] += 1
    return applied
