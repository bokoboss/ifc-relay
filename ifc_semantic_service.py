from __future__ import annotations

from version import ENGINE_CONTRACT, SEMANTIC_SCHEMA_VERSION

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon
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


# Storey elevation vs. floor-slab top difference that is reported as a datum warning.
STOREY_DATUM_WARNING = 0.05
# Non-landing floor slabs within this distance of the storey floor are merged into
# it with a warning (steps, sunken wet areas, finishes). Further away they are left
# out of the walkable floor until the engineer includes them (sunscreens, canopies,
# mezzanines) - IFC predefined type FLOOR alone is not proof that a slab is walkable.
OFF_LEVEL_MERGE_MAX = 0.40
# Interior rings of merged floor regions smaller than this are slab-joint
# precision gaps, not pedestrian-relevant voids; no void mask is generated.
MIN_VOID_MASK_AREA = 0.05

# Moved helpers, re-exported: other modules and tests import them from here.
from semantic_geometry import (  # noqa: E402,F401
    EPS, WALKABLE_GAP_CLOSE, _farthest_pair, area_weighted_median, hole_polygons, largest_polygon,
    merge_walkable_components, mesh_bounds, mesh_footprint, polygon_components, polygon_points,
    precision_clean_polygon, split_out_holes,
)
from semantic_obstacles import (  # noqa: E402,F401
    PLATE_MAX_BOTTOM, PLATE_MIN_TOP, build_columns_and_obstacles, merge_stacked_panels,
)
from semantic_walls import (  # noqa: E402,F401
    PASSAGE_MAX_SILL, PASSAGE_MIN_HEIGHT, PASSAGE_MIN_WIDTH, STOREY_CONTINUATION_MIN, WALL_POLYGON_SOLIDITY,
    _door_relationships, _filled_opening_ids, _opening_shape, _opening_shape_polygon, axis_from_footprint,
    classify_unfilled_opening, opening_at_walking_height, project_point_to_axis, replicate_across_storeys,
    split_wall_axis, wall_footprint_solidity, wall_storey_bands,
)


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

    # Elements IfcOpenShell could not tessellate are missing from this model: say so.
    mesh_failed = geometry_payload.get("mesh_failures") or []
    if mesh_failed:
        failed_ids = []
        for failure in mesh_failed:
            try:
                failed_ids.append(global_id(model.by_id(int(failure.get("shape_id")))) or str(failure.get("shape_id")))
            except Exception:  # noqa: BLE001 - unknown id: keep the number
                failed_ids.append(str(failure.get("shape_id")))
        warnings.append(
            f"{len(mesh_failed)} element(s) could not be tessellated by IfcOpenShell and are missing from the "
            f"pedestrian model (first: {mesh_failed[0].get('error')})."
        )
        diag("mesh_failed", failed_ids, count=len(mesh_failed))

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

    gap_repairs: list[dict[str, Any]] = []
    for level_key in sorted(walkable_components_by_level):
        source_components = walkable_components_by_level[level_key]
        gap_stats: dict[str, Any] = {}
        merged_regions = merge_walkable_components(source_components, grid_size=0.005, stats=gap_stats)
        for piece in gap_stats.get("repairs", []):
            c = piece.centroid
            gap_repairs.append({"level_key": level_key, "centroid": [round(c.x, 2), round(c.y, 2)],
                                "area_m2": round(piece.area, 4),
                                "length_m": round(max(piece.length / 2, 0.0), 2)})
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
    columns, obstacles = build_columns_and_obstacles(
        model, prepend=[*generated_void_masks, *polygon_wall_obstacles],
        is_included=lambda element: effective_status(element, selection_overrides) == "include",
        mesh_by_id=mesh_by_id, resolve_level_key=resolve_level_key,
        level_z_by_key=level_z_by_key, levels=levels, warnings=warnings,
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
    from manual_edits import apply_manual_edits, edit_revision, edit_shape_type, polygon_fingerprint
    manual_status: dict[str, dict[str, Any]] = {}
    exit_anchors: list[dict[str, Any]] = []
    manual_applied = apply_manual_edits(
        manual_edits or [], areas=areas, walls=walls, obstacles=obstacles,
        level_z={int(lv["key"]): float(lv["z"]) for lv in levels}, warnings=warnings,
        status=manual_status, anchors=exit_anchors,
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
            "anchors": exit_anchors,
        })
        warnings.extend(connectivity_warnings(connectivity))
        for aid, hits in (connectivity.get("anchors") or {}).items():
            if aid in manual_status:
                manual_status[aid]["zones_touched"] = hits
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
            "gap_repairs": gap_repairs,
            "diagnostics": diagnostics,
            "connectivity": connectivity,
            "manual_edits": list(manual_edits or []),
            # Immutable record of inputs actually used by this semantic generation.
            # Keeping both UID and normalized geometry prevents a revised E1 from
            # inheriting the old E1's 'applied' review status after PATCH.
            "manual_edits_snapshot": [
                {
                    "id": e.get("id"),
                    "uid": e.get("uid") or e.get("created_at"),
                    "revision": edit_revision(e),
                    "shape_type": edit_shape_type(e),
                    "polygon_fingerprint": polygon_fingerprint(e.get("polygon")),
                }
                for e in manual_edits or []
            ],
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


def build_semantic_to_file(path: Path, output_path: Path, overrides: dict[str, str],
                           manual_edits: list[dict[str, Any]] | None, *,
                           geometry_cache_path: Path | None, geometry_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Worker-process entry for "prepare pedestrian model": tessellate (or reuse
    cached geometry), build the semantic model and write it to ``output_path``.
    Returns only the summary and warnings; the server reads the file."""
    from ifc_geometry_service import extract_ifc_geometry

    geometry = extract_ifc_geometry(path, cache_path=geometry_cache_path, **geometry_kwargs)
    model = build_semantic_model(path, geometry, overrides, manual_edits or [])
    write_semantic_model(output_path, model)
    info = model["ifc_semantic"]
    return {"summary": info["summary"], "warnings": info["warnings"],
            "outcome": "partial" if geometry.get("mesh_failures") else "success"}
