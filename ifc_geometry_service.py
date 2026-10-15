from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Any, Iterable

from ifc_service import (
    _imports,
    entity_name,
    global_id,
    is_a,
    recommendation,
    resolve_storey,
    storey_lookup,
)


SKIP_TYPES = (
    "IfcOpeningElement",
    "IfcSite",
    "IfcBuilding",
    "IfcBuildingStorey",
    "IfcProject",
)

# These classes are sufficient for a useful pedestrian-simulation source view.
# IfcWindow is intentionally retained as wall-closure context even though it is
# not exported as a separate Vissim object.
SIMULATION_RELEVANT_TYPES = (
    "IfcWall",
    "IfcDoor",
    "IfcWindow",
    "IfcSlab",
    "IfcColumn",
    "IfcStair",
    "IfcStairFlight",
    "IfcRamp",
    "IfcRampFlight",
    "IfcRailing",
    "IfcTransportElement",
    "IfcFurnishingElement",
    "IfcBuildingElementProxy",
    "IfcCurtainWall",
)


def _skip(entity: Any) -> bool:
    return any(is_a(entity, ifc_type) for ifc_type in SKIP_TYPES)


def _is_simulation_relevant(entity: Any) -> bool:
    if not any(is_a(entity, ifc_type) for ifc_type in SIMULATION_RELEVANT_TYPES):
        return False

    status, _, role = recommendation(entity)

    # Structural/system elements that are normally excluded should not be sent
    # to the browser in the default large-model view. Windows are a special
    # case: they remain useful visual closure context.
    if role == "wall_closure":
        return True

    # Review candidates remain available in the simulation-relevant view so the
    # engineer can explicitly promote/reject them.
    return status in {"include", "review"}


def _round_list(values: Any, digits: int = 6) -> list[float]:
    return [round(float(v), digits) for v in values]


def _bounds(verts: list[float]) -> dict[str, list[float]]:
    if not verts:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]}

    xs = verts[0::3]
    ys = verts[1::3]
    zs = verts[2::3]
    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
    }


def _merge_bounds(
    current: dict[str, list[float]] | None,
    item: dict[str, list[float]],
) -> dict[str, list[float]]:
    if current is None:
        return {"min": list(item["min"]), "max": list(item["max"])}

    return {
        "min": [min(current["min"][i], item["min"][i]) for i in range(3)],
        "max": [max(current["max"][i], item["max"][i]) for i in range(3)],
    }


def _selected_elements(
    model: Any,
    util_element: Any,
    *,
    mode: str,
    storey_ids: set[int] | None,
) -> tuple[list[Any], dict[int, Any]]:
    if mode not in {"simulation_relevant", "full"}:
        raise ValueError(f"Unsupported geometry mode: {mode}")

    lookup = storey_lookup(model)
    result: list[Any] = []

    for entity in model.by_type("IfcElement"):
        if _skip(entity) or getattr(entity, "Representation", None) is None:
            continue

        if mode == "simulation_relevant" and not _is_simulation_relevant(entity):
            continue

        if storey_ids:
            storey = resolve_storey(entity, lookup, util_element)
            if storey is None or int(storey.id()) not in storey_ids:
                continue

        result.append(entity)

    return result, lookup


def extract_ifc_geometry(
    path: Path,
    cache_path: Path | None = None,
    max_elements: int = 12000,
    *,
    mode: str = "simulation_relevant",
    storey_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Extract browser/semantic mesh geometry with large-model filtering.

    Parameters
    ----------
    mode:
        ``simulation_relevant`` filters out classes such as beams/MEP/roof that
        do not normally contribute to the pedestrian footprint. ``full`` keeps
        all meshable IfcElement instances.
    storey_ids:
        Optional set/list of IfcBuildingStorey entity IDs. This is the lazy-load
        mechanism used by the browser. Semantic generation normally requests
        all storeys with ``simulation_relevant`` mode.
    """
    requested_storeys = {int(v) for v in (storey_ids or [])}

    if cache_path is not None and cache_path.exists():
        source_mtime = path.stat().st_mtime
        cache_mtime = cache_path.stat().st_mtime
        if cache_mtime >= source_mtime:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            meta = cached.get("request", {})
            if (
                meta.get("mode") == mode
                and {int(v) for v in meta.get("storey_ids", [])} == requested_storeys
            ):
                return cached

    ifcopenshell, util_element, _ = _imports()
    import ifcopenshell.geom

    model = ifcopenshell.open(str(path))
    elements, lookup = _selected_elements(
        model,
        util_element,
        mode=mode,
        storey_ids=requested_storeys or None,
    )

    if len(elements) > max_elements:
        raise ValueError(
            f"IFC geometry request contains {len(elements)} meshable elements, "
            f"above safety limit {max_elements}. Use simulation-relevant or "
            "storey-filtered loading instead of full-model loading."
        )

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("apply-default-materials", True)

    num_threads = max(1, min(8, multiprocessing.cpu_count()))
    iterator = ifcopenshell.geom.iterator(
        settings,
        model,
        num_threads,
        include=elements,
    )

    result_elements: list[dict[str, Any]] = []
    model_bounds = None
    failures: list[dict[str, Any]] = []
    total_triangles = 0
    total_vertices = 0

    if iterator.initialize():
        while True:
            shape = None
            try:
                shape = iterator.get()
                element = model.by_id(shape.id)
                geom = shape.geometry

                verts = _round_list(geom.verts)
                faces = [int(v) for v in geom.faces]

                if verts and faces:
                    storey = resolve_storey(element, lookup, util_element)
                    rec, mapping, role = recommendation(element)
                    bbox = _bounds(verts)
                    model_bounds = _merge_bounds(model_bounds, bbox)
                    total_vertices += len(verts) // 3
                    total_triangles += len(faces) // 3

                    result_elements.append(
                        {
                            "entity_id": int(element.id()),
                            "global_id": global_id(element),
                            "ifc_type": str(element.is_a()),
                            "name": entity_name(
                                element,
                                f"{element.is_a()} #{element.id()}",
                            ),
                            "storey_id": int(storey.id()) if storey is not None else None,
                            "storey_name": (
                                entity_name(storey, f"Storey #{storey.id()}")
                                if storey is not None
                                else None
                            ),
                            "recommendation": rec,
                            "viswalk_mapping": mapping,
                            "simulation_role": role,
                            "vertices": verts,
                            "indices": faces,
                            "bounds": bbox,
                        }
                    )
            except Exception as exc:
                failures.append(
                    {
                        "shape_id": int(getattr(shape, "id", -1) or -1),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

            if not iterator.next():
                break

    if model_bounds is None:
        model_bounds = {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}

    categories: dict[str, int] = {}
    storeys: dict[str, int] = {}
    storey_ids_by_name: dict[str, int] = {}
    role_counts: dict[str, int] = {}

    for item in result_elements:
        categories[item["ifc_type"]] = categories.get(item["ifc_type"], 0) + 1
        storey_key = item["storey_name"] or "Unassigned"
        storeys[storey_key] = storeys.get(storey_key, 0) + 1
        if item.get("storey_id") is not None:
            storey_ids_by_name[storey_key] = int(item["storey_id"])
        role = item["simulation_role"]
        role_counts[role] = role_counts.get(role, 0) + 1

    payload = {
        "schema_version": "0.4.1",
        "source_file": str(path),
        "request": {
            "mode": mode,
            "storey_ids": sorted(requested_storeys),
            "filtered": mode != "full" or bool(requested_storeys),
        },
        "candidate_element_count": len(elements),
        "element_count": len(result_elements),
        "mesh_failures": failures,
        "triangle_count": total_triangles,
        "vertex_count": total_vertices,
        "bounds": model_bounds,
        "categories": categories,
        "storeys": storeys,
        "storey_ids_by_name": storey_ids_by_name,
        "simulation_roles": role_counts,
        "elements": result_elements,
        "preview_note": (
            "Large Model Mode: browser geometry is filtered independently from "
            "the authoritative semantic build. Source mode shows the requested "
            "IFC subset; Simulation Preview uses the generated semantic model."
        ),
    }

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )

    return payload
