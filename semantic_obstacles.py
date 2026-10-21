"""Columns and generic movement obstacles for the pedestrian (semantic) model.

Included IFC elements other than walls, slabs, doors/windows, openings and
stairs become columns (circle or rectangle) or polygon obstacles on their
storey. Curtain-wall panels (IfcPlate/IfcMember) go to the storey whose walking
zone they stand in; panels stacked on one footprint are merged.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from ifc_service import entity_name, global_id, is_a, recommendation
from semantic_geometry import EPS, largest_polygon, mesh_bounds, mesh_footprint, polygon_points
from semantic_walls import axis_from_footprint


# IfcPlate/IfcMember block walking only where they stand in the walking zone:
# a plate whose top is below this (a floor deck) or whose bottom is above this
# (a canopy, a ceiling panel) relative to its level is not an obstacle.
PLATE_MIN_TOP = 0.30
PLATE_MAX_BOTTOM = 2.00


def merge_stacked_panels(obstacles: list[dict[str, Any]]) -> int:
    """Curtain-wall rails and panels often repeat on one footprint every few
    centimetres up the wall (model C: 464 rails, 0.1 m apart). Vissim obstacles are
    footprints with a height, so one obstacle per footprint covers them all.
    Merges in place; returns how many obstacles were folded into another."""
    groups: dict[tuple[Any, ...], list[int]] = {}
    for idx, obs in enumerate(obstacles):
        if obs.get("type") not in ("IfcPlate", "IfcMember") or not obs.get("polygon"):
            continue
        ring = tuple(sorted((round(float(x), 2), round(float(y), 2)) for x, y in obs["polygon"]))
        groups.setdefault((int(obs["level_key"]), ring), []).append(idx)
    drop: set[int] = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = obstacles[members[0]]
        bottom = min(float(obstacles[i]["z_offset"]) for i in members)
        top = max(float(obstacles[i]["z_offset"]) + float(obstacles[i]["height"]) for i in members)
        guids = [obstacles[i].get("ifc_global_id") for i in members if obstacles[i].get("ifc_global_id")]
        keep["z_offset"] = round(bottom, 5)
        keep["height"] = round(top - bottom, 5)
        keep["ifc_source_global_ids"] = guids
        keep["name"] = f"{keep['name']} (+{len(members) - 1} stacked)"
        drop.update(members[1:])
    if drop:
        obstacles[:] = [o for i, o in enumerate(obstacles) if i not in drop]
    return len(drop)


def build_columns_and_obstacles(model: Any, *, prepend: list[dict[str, Any]],
                                is_included: Callable[[Any], bool],
                                mesh_by_id: dict[int, dict[str, Any]],
                                resolve_level_key: Callable[[Any], int | None],
                                level_z_by_key: dict[int, float], levels: list[dict[str, Any]],
                                warnings: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Columns and obstacles, keyed from 1301 / 1401; ``prepend`` obstacles come first."""
    columns: list[dict[str, Any]] = []
    obstacles: list[dict[str, Any]] = []
    plates_off_walking_height = 0
    column_key = 1301
    obstacle_key = 1401

    for generated in prepend:                 # floor-void masks, then polygon walls
        obstacles.append({"key": obstacle_key, **generated})
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

        if not is_included(element):
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
        if is_a(element, "IfcPlate") or is_a(element, "IfcMember"):
            # Curtain-wall panels belong to the storey of their curtain wall, which
            # can span many storeys: put each panel on the storey whose walking
            # zone it stands in, and drop floor decks and overhead panels.
            walking = [int(lv["key"]) for lv in sorted(levels, key=lambda lv: float(lv["z"]))
                       if not lv.get("generated")
                       and bbmax[2] - level_z_by_key[int(lv["key"])] >= PLATE_MIN_TOP
                       and bbmin[2] - level_z_by_key[int(lv["key"])] <= PLATE_MAX_BOTTOM]
            if not walking:
                plates_off_walking_height += 1
                continue
            at_or_below = [k for k in walking if level_z_by_key[k] <= bbmin[2] + PLATE_MIN_TOP]
            level_key = at_or_below[-1] if at_or_below else walking[0]
            z_offset = bbmin[2] - level_z_by_key[level_key]
            if abs(z_offset) < 1e-5:
                z_offset = 0.0

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
    stacked = merge_stacked_panels(obstacles)
    if stacked:
        warnings.append(
            f"{stacked} curtain-wall plate/member obstacle(s) stacked on the same footprint were merged "
            "into one obstacle each (their GlobalIds are kept on the merged obstacle)."
        )
    if plates_off_walking_height:
        warnings.append(
            f"{plates_off_walking_height} IfcPlate/IfcMember element(s) not at walking height "
            f"(top below {PLATE_MIN_TOP:.2f} m or bottom above {PLATE_MAX_BOTTOM:.2f} m over their level); not exported as obstacles."
        )
    return columns, obstacles
