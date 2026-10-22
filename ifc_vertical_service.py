"""Geometry-aware vertical circulation for the semantic model (v0.5 draft).

Converts IFC stairs and ramps into Geometry Engine vertical-connection records
using the triangulated mesh that is already cached for the 3D review, instead
of assuming that every stair connects its storey to the next storey.

Principles (see docs/VERTICAL_CIRCULATION.md):

* One record per straight flight. A parent ``IfcStair``/``IfcRamp`` is
  decomposed into its ``IfcStairFlight``/``IfcRampFlight`` children when they
  carry geometry; the parent mesh is used only when there are no meshable
  children.
* Start/end heights come from the flight mesh (lowest and highest vertex), and
  the low end is found from the geometry, not from the polygon winding.
* Each end is snapped to the nearest known level within a tolerance. Known
  levels are IFC storeys plus generated *landing levels* created from
  intermediate landing slabs. An end that matches no level keeps an explicit
  z offset and raises a warning; nothing is silently assumed.

All functions here are deterministic and free of COM/Vissim dependencies.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable

from shapely.geometry import Polygon

from ifc_service import entity_name, global_id, is_a


# A Revit flight typically ends one riser (about 0.15-0.19 m) below the upper
# landing when "end with riser" is off, so the snap tolerance must exceed one
# riser but stay well below a storey height.
LEVEL_SNAP_TOLERANCE = 0.25
# Landing slabs whose walking surface is further than this above/below their
# storey are treated as intermediate landings, not as part of the storey floor.
INTERMEDIATE_LANDING_THRESHOLD = 0.25
# Minimum rise for a vertical connection; anything flatter is reported.
MIN_RISE = 0.05
# Footprint/rectangle area ratio below which the flight is not straight.
STRAIGHTNESS_WARNING = 0.85
# Fraction of the run length sampled at each end to find the low/high end.
END_SAMPLE_FRACTION = 0.2
# Minimum height difference between the two ends (as a fraction of the rise)
# for the up-direction to count as derived from geometry.
DIRECTION_MIN_END_SEPARATION = 0.5
# Generated landing level keys start here to keep storey keys (1..N) stable.
LANDING_LEVEL_KEY_START = 901
DEFAULT_RISER_HEIGHT = 0.17
# Engine v0.3 validation requires each ramp/stair end to overlap (not just
# touch) the walkable area of its level. IFC flights usually only abut the
# landing, so the polygon is extended this far beyond both ends of the run.
END_OVERLAP = 0.10

STAIR_TYPES = ("IfcStair", "IfcStairFlight")
RAMP_TYPES = ("IfcRamp", "IfcRampFlight")
FLIGHT_TYPES = ("IfcStairFlight", "IfcRampFlight")
PARENT_TYPES = ("IfcStair", "IfcRamp")


def is_vertical_element(entity: Any) -> bool:
    return any(is_a(entity, t) for t in STAIR_TYPES + RAMP_TYPES)


def _mesh_coords(vertices: list[float]) -> list[tuple[float, float, float]]:
    return [
        (float(vertices[i]), float(vertices[i + 1]), float(vertices[i + 2]))
        for i in range(0, len(vertices) - 2, 3)
    ]


def flight_profile(
    vertices: list[float],
    footprint: Polygon | None,
) -> dict[str, Any] | None:
    """Describe a straight flight from its mesh vertices and 2D footprint.

    Returns the run axis oriented from the low end to the high end, the
    oriented rectangle (bottom edge first), heights, and a straightness score.
    Returns ``None`` when the geometry is unusable.
    """
    coords = _mesh_coords(vertices)
    if footprint is None or footprint.area <= 1e-8 or len(coords) < 4:
        return None

    rect = footprint.minimum_rotated_rectangle
    if not isinstance(rect, Polygon):
        return None
    corners = list(rect.exterior.coords)[:-1]
    if len(corners) != 4:
        return None

    # Edge 0-1 vs 1-2: the longer one is the run direction.
    e01 = math.dist(corners[0], corners[1])
    e12 = math.dist(corners[1], corners[2])
    if e01 >= e12:
        run_vec = (corners[1][0] - corners[0][0], corners[1][1] - corners[0][1])
        run_length, width = e01, e12
    else:
        run_vec = (corners[2][0] - corners[1][0], corners[2][1] - corners[1][1])
        run_length, width = e12, e01
    if run_length <= 1e-6:
        return None
    ux, uy = run_vec[0] / run_length, run_vec[1] / run_length

    cx, cy = rect.centroid.x, rect.centroid.y

    def t_of(x: float, y: float) -> float:
        return (x - cx) * ux + (y - cy) * uy

    half = run_length / 2.0
    band = max(run_length * END_SAMPLE_FRACTION, 1e-3)
    low_side = [z for x, y, z in coords if t_of(x, y) <= -half + band]
    high_side = [z for x, y, z in coords if t_of(x, y) >= half - band]
    if not low_side or not high_side:
        return None

    # The walking surface is the top of the solid, so compare the highest
    # vertex near each end. Swap the axis if the "high" sample is lower.
    end_gap = abs(max(high_side) - max(low_side))
    if max(low_side) > max(high_side):
        ux, uy = -ux, -uy

    z_values = [c[2] for c in coords]
    z_bottom = min(z_values)
    z_top = max(z_values)
    end_separation = end_gap / (z_top - z_bottom) if z_top - z_bottom > 1e-9 else 0.0

    # Perpendicular unit vector for the rectangle width.
    px, py = -uy, ux
    bottom_center = (cx - ux * half, cy - uy * half)
    top_center = (cx + ux * half, cy + uy * half)
    hw = width / 2.0
    oriented = [
        (bottom_center[0] - px * hw, bottom_center[1] - py * hw),
        (bottom_center[0] + px * hw, bottom_center[1] + py * hw),
        (top_center[0] + px * hw, top_center[1] + py * hw),
        (top_center[0] - px * hw, top_center[1] - py * hw),
    ]

    straightness = float(footprint.area / rect.area) if rect.area > 1e-9 else 0.0

    return {
        "polygon": [[round(x, 5), round(y, 5)] for x, y in oriented],
        "bottom_edge": [[round(x, 5), round(y, 5)] for x, y in oriented[:2]],
        "top_edge": [[round(x, 5), round(y, 5)] for x, y in oriented[2:]],
        "bottom_center": [round(bottom_center[0], 5), round(bottom_center[1], 5)],
        "top_center": [round(top_center[0], 5), round(top_center[1], 5)],
        "run_length": float(run_length),
        "width": float(width),
        "z_bottom": float(z_bottom),
        "z_top": float(z_top),
        "rise": float(z_top - z_bottom),
        "straightness": straightness,
        "end_separation": float(end_separation),
    }


def extend_run(profile: dict[str, Any], overlap: float = END_OVERLAP) -> list[list[float]]:
    """Oriented rectangle (bottom edge first) lengthened by ``overlap`` at both ends."""
    (bx, by), (tx, ty) = profile["bottom_center"], profile["top_center"]
    length = math.hypot(tx - bx, ty - by)
    if length <= 1e-9:
        return profile["polygon"]
    ux, uy = (tx - bx) / length, (ty - by) / length
    px, py = -uy, ux
    hw = profile["width"] / 2.0
    b = (bx - ux * overlap, by - uy * overlap)
    t = (tx + ux * overlap, ty + uy * overlap)
    pts = [
        (b[0] - px * hw, b[1] - py * hw),
        (b[0] + px * hw, b[1] + py * hw),
        (t[0] + px * hw, t[1] + py * hw),
        (t[0] - px * hw, t[1] - py * hw),
    ]
    return [[round(x, 5), round(y, 5)] for x, y in pts]


def distinct_end_level(
    z_top: float,
    start_key: int,
    levels: list[dict[str, Any]],
) -> tuple[int, float] | None:
    """Engine v0.3 rejects start_level == end_level, so express a flight that
    ends between levels relative to the nearest *other* level: preferably the
    one above (negative offset), otherwise the nearest one below."""
    others = [lv for lv in levels if int(lv["key"]) != int(start_key)]
    if not others:
        return None
    # Prefer storey levels: a generated landing level elsewhere in the
    # building has no area under this flight.
    storeys = [lv for lv in others if not lv.get("generated")]
    others = storeys or others
    above = [lv for lv in others if float(lv["z"]) >= z_top]
    pool = above or others
    best = min(pool, key=lambda lv: abs(float(lv["z"]) - z_top))
    return int(best["key"]), round(z_top - float(best["z"]), 5)


def direction_assessment(profile: dict[str, Any]) -> tuple[str, str]:
    """Is the up-direction derived reliably from geometry?

    Returns ``(status, reason)`` with status ``derived_from_geometry`` or
    ``needs_review``. Even a derived direction is not certified until it has
    been checked in Vissim.
    """
    if profile["straightness"] < STRAIGHTNESS_WARNING:
        return "needs_review", "footprint is not a straight flight"
    if profile.get("end_separation", 0.0) < DIRECTION_MIN_END_SEPARATION:
        return "needs_review", "both ends of the flight reach similar heights"
    return "derived_from_geometry", "low and high ends found from the mesh"


def match_level(
    z: float,
    levels: list[dict[str, Any]],
    tolerance: float = LEVEL_SNAP_TOLERANCE,
) -> tuple[int, float, bool]:
    """Snap ``z`` to a level.

    Returns ``(level_key, z_offset, exact)``. ``exact`` is True when a level is
    within ``tolerance`` (offset is then 0). Otherwise the nearest level below
    ``z`` (or the lowest level) is returned with an explicit offset.
    """
    if not levels:
        raise ValueError("No levels available for vertical-connection matching.")

    nearest = min(levels, key=lambda lv: abs(float(lv["z"]) - z))
    if abs(float(nearest["z"]) - z) <= tolerance:
        return int(nearest["key"]), 0.0, True

    below = [lv for lv in levels if float(lv["z"]) <= z]
    base = max(below, key=lambda lv: float(lv["z"])) if below else min(
        levels, key=lambda lv: float(lv["z"])
    )
    return int(base["key"]), round(z - float(base["z"]), 5), False


def is_intermediate_landing(
    slab_top_z: float,
    storey_z: float,
    threshold: float = INTERMEDIATE_LANDING_THRESHOLD,
) -> bool:
    return abs(slab_top_z - storey_z) > threshold


def cluster_landing_levels(
    landing_tops: list[float],
    storey_levels: list[dict[str, Any]],
    tolerance: float = LEVEL_SNAP_TOLERANCE,
    key_start: int = LANDING_LEVEL_KEY_START,
) -> list[dict[str, Any]]:
    """Create generated levels for intermediate landing heights.

    Heights within ``tolerance`` of each other share one generated level
    (Vissim levels are global planes). Heights that already match a storey are
    not duplicated.
    """
    levels: list[dict[str, Any]] = []
    for z in sorted(landing_tops):
        if any(abs(float(lv["z"]) - z) <= tolerance for lv in storey_levels):
            continue
        if levels and abs(levels[-1]["_zs"][-1] - z) <= tolerance:
            levels[-1]["_zs"].append(z)
            continue
        levels.append({"_zs": [z]})

    result = []
    for i, item in enumerate(levels):
        z = sum(item["_zs"]) / len(item["_zs"])
        result.append(
            {
                "key": key_start + i,
                "name": f"Landing +{z:.2f}",
                "z": round(z, 6),
                "generated": True,
                "generated_from": "intermediate_landing_slab",
            }
        )
    return result


def _riser_count(entity: Any) -> int | None:
    for attr in ("NumberOfRisers", "NumberOfRiser"):
        value = getattr(entity, attr, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def collect_vertical_units(
    model: Any,
    is_included: Callable[[Any], bool],
    is_explicitly_excluded: Callable[[Any], bool],
    children_of: dict[int, list[Any]],
    parent_of: dict[int, Any],
    has_mesh: Callable[[Any], bool],
) -> tuple[list[tuple[Any, Any | None]], list[str]]:
    """Return ``(element, parent)`` pairs to convert, one per flight.

    * Included parent with meshable flight children -> each child flight
      (unless that child is explicitly excluded).
    * Included parent without meshable children -> the parent itself.
    * Included flight whose parent was not already decomposed -> the flight.
    """
    units: list[tuple[Any, Any | None]] = []
    warnings: list[str] = []
    seen: set[int] = set()

    for parent_type in PARENT_TYPES:
        for parent in model.by_type(parent_type):
            if not is_included(parent):
                continue
            flights = [
                c
                for c in children_of.get(int(parent.id()), [])
                if any(is_a(c, t) for t in FLIGHT_TYPES)
            ]
            meshable = [c for c in flights if has_mesh(c)]
            if meshable:
                for child in meshable:
                    if is_explicitly_excluded(child):
                        continue
                    seen.add(int(child.id()))
                    units.append((child, parent))
            elif has_mesh(parent):
                seen.add(int(parent.id()))
                units.append((parent, None))
            else:
                warnings.append(
                    f"{parent.is_a()} {global_id(parent) or parent.id()} is included but neither it nor its flights have meshable geometry."
                )
            seen.add(int(parent.id()))

    for flight_type in FLIGHT_TYPES:
        for flight in model.by_type(flight_type):
            if int(flight.id()) in seen or not is_included(flight):
                continue
            seen.add(int(flight.id()))
            units.append((flight, parent_of.get(int(flight.id()))))

    return units, warnings


def build_vertical_connections(
    units: list[tuple[Any, Any | None]],
    mesh_for: Callable[[Any], dict[str, Any] | None],
    footprint_for: Callable[[dict[str, Any]], Polygon | None],
    all_levels: list[dict[str, Any]],
    key_start: int = 2001,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Convert flight units into engine vertical-connection records."""
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    key = key_start
    level_z = {int(lv["key"]): float(lv["z"]) for lv in all_levels}

    for element, parent in units:
        label = f"{element.is_a()} {global_id(element) or element.id()}"
        mesh = mesh_for(element)
        if mesh is None:
            warnings.append(f"Vertical element {label} has no cached mesh; skipped.")
            continue
        footprint = footprint_for(mesh)
        profile = flight_profile(mesh.get("vertices", []), footprint)
        if profile is None:
            warnings.append(f"Vertical element {label} produced no usable flight footprint; skipped.")
            continue
        if profile["rise"] < MIN_RISE:
            warnings.append(
                f"Vertical element {label} rises only {profile['rise']:.3f} m; not converted. Review whether it is a landing or a flat ramp."
            )
            continue
        if profile["straightness"] < STRAIGHTNESS_WARNING:
            warnings.append(
                f"Vertical element {label} is not a straight flight (footprint fills {profile['straightness']:.0%} of its rectangle); verify run direction and extent in 3D review."
            )

        start_key, start_off, start_exact = match_level(profile["z_bottom"], all_levels)
        end_key, end_off, end_exact = match_level(profile["z_top"], all_levels)

        if start_key == end_key and start_off == end_off:
            warnings.append(
                f"Vertical element {label} starts and ends on the same level; skipped."
            )
            continue
        if start_key == end_key:
            alt = distinct_end_level(profile["z_top"], start_key, all_levels)
            if alt is None:
                warnings.append(
                    f"Vertical element {label} ends between levels and the model has no other level to reference; skipped."
                )
                continue
            end_key, end_off = alt
        for which, exact, z in (("bottom", start_exact, profile["z_bottom"]), ("top", end_exact, profile["z_top"])):
            if not exact:
                warnings.append(
                    f"Vertical element {label}: {which} at z={z:.3f} m matches no storey or landing level within {LEVEL_SNAP_TOLERANCE:.2f} m; z offset used. Verify connection in Vissim."
                )

        source = parent if parent is not None else element
        conn_type = "stairway" if any(is_a(source, t) for t in STAIR_TYPES) or any(
            is_a(element, t) for t in STAIR_TYPES
        ) else "ramp"

        name = entity_name(element, "")
        if not name and parent is not None:
            name = entity_name(parent, "")
        name = name or f"IFC Vertical {element.id()}"

        direction_status, direction_reason = direction_assessment(profile)
        if direction_status == "needs_review":
            warnings.append(
                f"Vertical element {label}: up-direction could not be determined reliably ({direction_reason}); "
                "check the arrow in the pedestrian-model view."
            )

        record: dict[str, Any] = {
            "key": key,
            "name": name,
            "type": conn_type,
            "start_level": start_key,
            "end_level": end_key,
            "start_z_offset": start_off,
            "end_z_offset": end_off,
            "polygon": extend_run(profile),
            "end_overlap": END_OVERLAP,
            "thickness": 0.20,
            "show_balustrade": True,
            "ifc_global_id": global_id(element),
            "ifc_entity_id": int(element.id()),
            "ifc_parent_global_id": global_id(parent) if parent is not None else None,
            "geometry_source": "ifc_mesh",
            "polygon_order": "bottom_edge_first",
            # True flight edges (without the END_OVERLAP extension).
            "bottom_edge": profile["bottom_edge"],
            "top_edge": profile["top_edge"],
            "z_bottom": round(profile["z_bottom"], 5),
            "z_top": round(profile["z_top"], 5),
            "rise": round(profile["rise"], 5),
            "run_length": round(profile["run_length"], 5),
            "width": round(profile["width"], 5),
            "direction_status": direction_status,
            "direction_reason": direction_reason,
            "direction_certified": False,
            "level_match": {
                "start": "exact" if start_exact else "offset",
                "end": "exact" if end_exact else "offset",
            },
        }
        if conn_type == "stairway":
            # Use the flight's own riser count only: a parent IfcStair count
            # covers all of its flights.
            steps = _riser_count(element)
            if steps is None:
                rise = (level_z[end_key] + end_off) - (level_z[start_key] + start_off)
                steps = max(1, int(round(rise / DEFAULT_RISER_HEIGHT)))
                record["steps_source"] = "estimated_from_rise"
            else:
                record["steps_source"] = "ifc_attribute"
            record["steps"] = steps

        records.append(record)
        key += 1

    return records, warnings


def children_map(model: Any) -> dict[int, list[Any]]:
    result: dict[int, list[Any]] = defaultdict(list)
    for rel in model.by_type("IfcRelAggregates"):
        parent = getattr(rel, "RelatingObject", None)
        if parent is None:
            continue
        for child in getattr(rel, "RelatedObjects", None) or []:
            result[int(parent.id())].append(child)
    return result


def stair_structure(model: Any, parent_of: dict[int, Any], children_of: dict[int, list[Any]]) -> list[dict[str, Any]]:
    """Stair/ramp units of the IFC, without decisions (cacheable per file).

    A unit is a parent ``IfcStair``/``IfcRamp`` (driving its flights) or a
    flight that has no parent stair/ramp."""
    units: list[dict[str, Any]] = []
    for parent_type in PARENT_TYPES:
        for parent in model.by_type(parent_type):
            flights = [c for c in children_of.get(int(parent.id()), []) if any(is_a(c, t) for t in FLIGHT_TYPES)]
            units.append({
                "driver": "parent",
                "global_id": global_id(parent),
                "name": entity_name(parent, ""),
                "kind": "stair" if is_a(parent, "IfcStair") else "ramp",
                "flights": len(flights),
                "flight_global_ids": [g for g in (global_id(f) for f in flights) if g],
            })
    for flight_type in FLIGHT_TYPES:
        for flight in model.by_type(flight_type):
            parent = parent_of.get(int(flight.id()))
            if parent is not None and any(is_a(parent, t) for t in PARENT_TYPES):
                continue
            units.append({
                "driver": "flight",
                "global_id": global_id(flight),
                "name": entity_name(flight, ""),
                "kind": "stair" if is_a(flight, "IfcStairFlight") else "ramp",
                "flights": 1,
                "flight_global_ids": [],
            })
    return units


def stair_overview_from_structure(structure: list[dict[str, Any]], overrides: dict[str, str]) -> dict[str, Any]:
    """Apply the engineer's decisions to the stair/ramp units (cheap; no IFC).

    Bulk actions set the decision on the drivers only; child flights follow
    their parent, and a child flight the engineer excluded explicitly stays
    excluded."""
    def decision(guid: str | None) -> str:
        return overrides.get(guid, "auto") if guid else "auto"

    units = []
    for base in structure:
        own = decision(base.get("global_id"))
        if base.get("driver") == "parent":
            child = [decision(g) for g in base.get("flight_global_ids", [])]
            if own == "include" or "include" in child:
                state = "include"
            elif own == "exclude":
                state = "exclude"
            else:
                state = "review"
            excluded = child.count("exclude")
        else:
            state = own if own in ("include", "exclude") else "review"
            excluded = 0
        unit = {k: v for k, v in base.items() if k != "driver"}
        unit.update(excluded_flights=excluded, state=state)
        units.append(unit)
    counts = {
        "units": len(units),
        "flights": sum(u["flights"] for u in units),
        "include": sum(1 for u in units if u["state"] == "include"),
        "review": sum(1 for u in units if u["state"] == "review"),
        "exclude": sum(1 for u in units if u["state"] == "exclude"),
    }
    return {"counts": counts, "units": units}


def stair_overview(model: Any, overrides: dict[str, str], parent_of: dict[int, Any],
                   children_of: dict[int, list[Any]]) -> dict[str, Any]:
    """Stair/ramp units for bulk review, without double counting."""
    return stair_overview_from_structure(stair_structure(model, parent_of, children_of), overrides)


def stair_structure_for_file(path: Any) -> list[dict[str, Any]]:
    """Worker-process entry: open the IFC and list its stair/ramp units."""
    import ifcopenshell

    from ifc_semantic_service import _parent_map

    model = ifcopenshell.open(str(path))
    return stair_structure(model, _parent_map(model), children_map(model))


def stair_overview_for_file(path: Any, overrides: dict[str, str]) -> dict[str, Any]:
    """Worker-process entry: open the IFC and summarise its stairs/ramps."""
    import ifcopenshell

    from ifc_semantic_service import _parent_map

    model = ifcopenshell.open(str(path))
    return stair_overview(model, overrides, _parent_map(model), children_map(model))


def audit_with_stairs(path: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Worker-process entry: one read of the IFC gives the audit and the stair
    units (a 371 MB IFC takes ~12 s just to open)."""
    from pathlib import Path

    import ifcopenshell

    from ifc_semantic_service import _parent_map
    from ifc_service import audit_ifc

    model = ifcopenshell.open(str(path))
    return audit_ifc(Path(path), model), stair_structure(model, _parent_map(model), children_map(model))
