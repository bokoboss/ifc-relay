from __future__ import annotations

from version import GEOMETRY_PAYLOAD_VERSION

import json
import multiprocessing
import os
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


# Bump when the extracted meshes change, so cached geometry of an older
# extractor is never reused (cache files carry it in their name).
EXTRACTOR_VERSION = "g2"


class GeometryFailed(RuntimeError):
    """No usable geometry: the message says why (shown to the engineer)."""


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
    "IfcPlate",
    "IfcMember",
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


def _placed_mesh(shape: Any, shared: dict[Any, tuple[Any, list[int]]]) -> tuple[list[float], list[int]]:
    """World vertices (rounded) and triangle indices of one iterator shape.

    The local mesh is read once per shared geometry; the shape's 4x4 placement
    (column-major) moves it to world coordinates. Same result as the iterator's
    world-coordinate mode."""
    import numpy as np

    geom = shape.geometry
    cached = shared.get(geom.id)
    if cached is None:
        cached = (np.asarray(geom.verts, dtype=float).reshape(-1, 3), [int(v) for v in geom.faces])
        shared[geom.id] = cached
    local, faces = cached
    m = np.asarray(shape.transformation.matrix, dtype=float).reshape(4, 4).T
    world = local @ m[:3, :3].T + m[:3, 3]
    return _round_list(world.ravel().tolist()), list(faces)


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


def _review_tier(entity: Any) -> bool:
    """Elements whose default rule is 'review' (proxies, furniture, transport,
    curtain walls). They can be slow to tessellate (furniture/proxy detail) and are
    not used by the pedestrian model unless the engineer includes them."""
    status, _, role = recommendation(entity)
    return status == "review" and role == "review"   # stairs (vertical_connection) stay in core


def _selected_elements(
    model: Any,
    util_element: Any,
    *,
    mode: str,
    storey_ids: set[int] | None,
    tier: str = "all",
    extra_guids: set[str] | None = None,
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

        if tier != "all":
            extra = bool(extra_guids) and getattr(entity, "GlobalId", None) in extra_guids
            in_review = _review_tier(entity)
            if tier == "core" and in_review and not extra:
                continue
            if tier == "review" and not in_review:
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
    tier: str = "all",
    extra_guids: Iterable[str] | None = None,
    source_sha256: str | None = None,
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
    extra = sorted({str(g) for g in (extra_guids or [])})

    if cache_path is not None and cache_path.exists():
        # Content-keyed caches (source_sha256) stay valid for a re-imported copy of
        # the same file; otherwise the cache must be newer than the IFC.
        fresh = (source_sha256 is not None) or cache_path.stat().st_mtime >= path.stat().st_mtime
        if fresh:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            meta = cached.get("request", {})
            if (
                meta.get("mode") == mode
                and {int(v) for v in meta.get("storey_ids", [])} == requested_storeys
                and meta.get("tier", "all") == tier
                and sorted(meta.get("extra_guids", [])) == extra
                and cached.get("source_sha256") == source_sha256
                and cached.get("extractor") == EXTRACTOR_VERSION
            ):
                try:
                    os.utime(cache_path)            # recently used: kept by the cache pruning
                except OSError:
                    pass
                return cached

    ifcopenshell, util_element, _ = _imports()
    import ifcopenshell.geom

    model = ifcopenshell.open(str(path))
    elements, lookup = _selected_elements(
        model,
        util_element,
        mode=mode,
        storey_ids=requested_storeys or None,
        tier=tier,
        extra_guids=set(extra),
    )

    if len(elements) > max_elements:
        raise ValueError(
            f"IFC geometry request contains {len(elements)} meshable elements, "
            f"above safety limit {max_elements}. Use simulation-relevant or "
            "storey-filtered loading instead of full-model loading "
            "(preparing the pedestrian model: raise VBB_SEMANTIC_MAX_ELEMENTS if the computer has the memory)."
        )

    # Local coordinates: elements that share a representation (mapped items,
    # repeated types) are tessellated once by the iterator and placed here with
    # their own transformation. World coordinates would tessellate every
    # instance again (measured: 451 s -> 27 s for one large model's review tier).
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", False)
    settings.set("apply-default-materials", True)
    shared: dict[Any, tuple[Any, list[int]]] = {}

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

    if elements and not iterator.initialize():
        raise GeometryFailed(
            f"IfcOpenShell could not start tessellating {len(elements)} element(s) of this IFC "
            "(the geometry iterator did not initialise). The file may use geometry this IfcOpenShell "
            "version cannot read; try loading one storey, or check the IFC in a BIM viewer."
        )
    if elements:
        while True:
            shape = None
            try:
                shape = iterator.get()
                element = model.by_id(shape.id)
                verts, faces = _placed_mesh(shape, shared)

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

    if elements and not result_elements:
        first = failures[0]["error"] if failures else "no triangles"
        raise GeometryFailed(
            f"None of the {len(elements)} element(s) produced a mesh ({len(failures)} failed; first: {first})."
        )

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
        "schema_version": GEOMETRY_PAYLOAD_VERSION,
        "source_file": str(path),
        "request": {
            "mode": mode,
            "storey_ids": sorted(requested_storeys),
            "tier": tier,
            "extra_guids": extra,
            "filtered": mode != "full" or bool(requested_storeys) or tier != "all",
        },
        "source_sha256": source_sha256,
        "extractor": EXTRACTOR_VERSION,
        # success: every element meshed; partial: some failed (listed in mesh_failures).
        "outcome": "partial" if failures else "success",
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


def extract_to_cache(path: Path, cache_path: Path, **kwargs: Any) -> dict[str, Any]:
    """Worker-process entry: extract (or reuse) geometry into ``cache_path`` and
    return only a summary, so the meshes never pass through the server process."""
    payload = extract_ifc_geometry(path, cache_path=cache_path, **kwargs)
    return {key: payload.get(key) for key in (
        "outcome", "element_count", "candidate_element_count", "triangle_count", "vertex_count",
        "mesh_failures", "storeys", "categories")}
