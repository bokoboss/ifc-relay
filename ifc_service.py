from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


INCLUDE_TYPES = (
    "IfcWall",
    "IfcWallStandardCase",
    "IfcDoor",
    "IfcSlab",
    "IfcColumn",
    "IfcStair",
    "IfcStairFlight",
    "IfcRamp",
    "IfcRampFlight",
    "IfcRailing",
)

REVIEW_TYPES = (
    "IfcTransportElement",
    "IfcFurnishingElement",
    "IfcBuildingElementProxy",
    "IfcCurtainWall",
    "IfcSpace",
)

EXCLUDE_TYPES = (
    "IfcDistributionElement",
    "IfcBeam",
    "IfcCovering",
    "IfcRoof",
    "IfcWindow",
)

# Geometry classes that are eligible for the default large-model 3D payload.
# Keep this aligned with ifc_geometry_service.SIMULATION_RELEVANT_TYPES.
SIMULATION_MESH_TYPES = (
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


def simulation_mesh_candidate(entity: Any) -> bool:
    """True when an IfcElement can appear in default simulation-relevant 3D."""
    if not any(is_a(entity, ifc_type) for ifc_type in SIMULATION_MESH_TYPES):
        return False
    if getattr(entity, "Representation", None) is None:
        return False
    status, _, role = recommendation(entity)
    if role == "wall_closure":
        return True
    return status in {"include", "review"}


def _imports():
    try:
        import ifcopenshell
        import ifcopenshell.util.element
        import ifcopenshell.util.unit
    except ImportError as exc:
        raise ImportError("IfcOpenShell is required for IFC processing.") from exc

    return (
        ifcopenshell,
        ifcopenshell.util.element,
        ifcopenshell.util.unit,
    )


def ifcopenshell_version() -> str | None:
    try:
        ifcopenshell, _, _ = _imports()
        return str(
            getattr(
                ifcopenshell,
                "version",
                getattr(ifcopenshell, "__version__", "unknown"),
            )
        )
    except ImportError:
        return None


def entity_name(entity: Any, fallback: str = "") -> str:
    value = getattr(entity, "Name", None)
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def global_id(entity: Any) -> str | None:
    value = getattr(entity, "GlobalId", None)
    return str(value) if value else None


def is_a(entity: Any, ifc_type: str) -> bool:
    try:
        return bool(entity.is_a(ifc_type))
    except Exception:
        return str(entity.is_a()) == ifc_type


def recommendation(entity: Any) -> tuple[str, str, str]:
    """Return (status, Viswalk mapping, simulation role)."""
    if is_a(entity, "IfcBuildingStorey"):
        return "include", "Viswalk Level", "level"

    if is_a(entity, "IfcOpeningElement"):
        return "exclude", "Relationship geometry; derive from Door/Window fill", "relationship"

    if is_a(entity, "IfcSite") or is_a(entity, "IfcBuilding"):
        return "exclude", "Spatial context only", "context"

    if is_a(entity, "IfcDoor"):
        return "include", "Pedestrian opening", "opening"

    if is_a(entity, "IfcWindow"):
        return (
            "exclude",
            "Wall closure context; not a separate Vissim object",
            "wall_closure",
        )

    if is_a(entity, "IfcSlab"):
        predefined = str(getattr(entity, "PredefinedType", "") or "").upper()
        if predefined in {"FLOOR", "LANDING"}:
            return "include", "Walkable area candidate", "walkable"
        if predefined == "BASESLAB":
            return (
                "review",
                "Foundation/base slab; include only when it is a pedestrian floor",
                "review",
            )
        if predefined == "ROOF":
            return "exclude", "Roof slab; not normally walkable simulation area", "none"
        return "review", "Review slab type before using as walkable area", "review"

    if is_a(entity, "IfcWall"):
        return "include", "Obstacle / physical wall segments", "obstacle"

    if is_a(entity, "IfcColumn"):
        return "include", "Obstacle", "obstacle"

    if is_a(entity, "IfcStair") or is_a(entity, "IfcStairFlight"):
        return (
            "review",
            "Vertical connection candidate; confirm start/end levels before build",
            "vertical_connection",
        )

    if is_a(entity, "IfcRamp") or is_a(entity, "IfcRampFlight"):
        return (
            "review",
            "Vertical connection candidate; confirm start/end levels before build",
            "vertical_connection",
        )

    if is_a(entity, "IfcRailing"):
        return "include", "Obstacle / boundary", "obstacle"

    for ifc_type in EXCLUDE_TYPES:
        if is_a(entity, ifc_type):
            return "exclude", "Not normally needed for pedestrian footprint", "none"

    for ifc_type in REVIEW_TYPES:
        if is_a(entity, ifc_type):
            mapping = {
                "IfcTransportElement": "Review: elevator/escalator/transport",
                "IfcFurnishingElement": "Review: obstacle if movement-relevant",
                "IfcBuildingElementProxy": "Review: classification ambiguous",
                "IfcCurtainWall": "Review: obstacle/boundary candidate",
                "IfcSpace": "Reference: may help walkable-space extraction",
            }.get(ifc_type, "Review")
            return "review", mapping, "review"

    return "review", "No simulation rule yet", "review"


def contained_storey_map(model: Any) -> dict[int, Any]:
    result: dict[int, Any] = {}

    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        structure = getattr(rel, "RelatingStructure", None)
        if structure is None or not is_a(structure, "IfcBuildingStorey"):
            continue

        for element in getattr(rel, "RelatedElements", None) or []:
            try:
                result[element.id()] = structure
            except Exception:
                pass

    return result


def decomposed_storey_map(model: Any) -> dict[int, Any]:
    result: dict[int, Any] = {}

    for rel in model.by_type("IfcRelAggregates"):
        parent = getattr(rel, "RelatingObject", None)
        if parent is None or not is_a(parent, "IfcBuildingStorey"):
            continue

        for child in getattr(rel, "RelatedObjects", None) or []:
            try:
                result[child.id()] = parent
            except Exception:
                pass

    return result


def storey_lookup(model: Any) -> dict[int, Any]:
    return {
        **decomposed_storey_map(model),
        **contained_storey_map(model),
    }


def resolve_storey(product: Any, lookup: dict[int, Any], util_element: Any) -> Any | None:
    storey = None
    try:
        storey = lookup.get(product.id())
    except Exception:
        pass

    if storey is None:
        try:
            container = util_element.get_container(product)
            if container is not None and is_a(container, "IfcBuildingStorey"):
                storey = container
        except Exception:
            pass

    return storey


def _opening_fill_breakdown(model: Any) -> dict[str, int]:
    result = Counter()

    for rel in model.by_type("IfcRelFillsElement"):
        fill = getattr(rel, "RelatedBuildingElement", None)
        if fill is None:
            result["unresolved"] += 1
        elif is_a(fill, "IfcDoor"):
            result["door"] += 1
        elif is_a(fill, "IfcWindow"):
            result["window"] += 1
        else:
            result[str(fill.is_a())] += 1

    return dict(result)


def audit_ifc(path: Path) -> dict[str, Any]:
    ifcopenshell, util_element, util_unit = _imports()
    model = ifcopenshell.open(str(path))

    unit_scale = float(util_unit.calculate_unit_scale(model))
    unit_entity = util_unit.get_project_unit(model, "LENGTHUNIT")

    if unit_entity is not None:
        try:
            unit_symbol = util_unit.get_unit_symbol(unit_entity)
        except Exception:
            unit_symbol = entity_name(unit_entity, unit_entity.is_a())
    else:
        unit_symbol = None

    project = next(iter(model.by_type("IfcProject")), None)
    sites = model.by_type("IfcSite")
    buildings = model.by_type("IfcBuilding")
    storeys = model.by_type("IfcBuildingStorey")
    lookup = storey_lookup(model)
    products = list(model.by_type("IfcProduct"))

    class_counts = Counter()
    recommendation_counts = Counter()
    storey_counts: dict[int, Counter] = defaultdict(Counter)
    storey_mesh_counts: Counter = Counter()

    element_rows = []
    proxy_count = 0
    no_storey_count = 0

    for product in products:
        ifc_type = str(product.is_a())
        class_counts[ifc_type] += 1

        rec, mapping, role = recommendation(product)
        recommendation_counts[rec] += 1

        if is_a(product, "IfcBuildingElementProxy"):
            proxy_count += 1

        storey = resolve_storey(product, lookup, util_element)

        if storey is not None:
            try:
                storey_counts[storey.id()][rec] += 1
                storey_counts[storey.id()]["total"] += 1
                if simulation_mesh_candidate(product):
                    storey_mesh_counts[storey.id()] += 1
            except Exception:
                pass
        elif not (
            is_a(product, "IfcSite")
            or is_a(product, "IfcBuilding")
            or is_a(product, "IfcBuildingStorey")
        ):
            no_storey_count += 1

        if len(element_rows) < 2000:
            element_rows.append(
                {
                    "entity_id": product.id(),
                    "global_id": global_id(product),
                    "ifc_type": ifc_type,
                    "name": entity_name(product, f"{ifc_type} #{product.id()}"),
                    "storey": entity_name(storey, f"Storey #{storey.id()}") if storey is not None else None,
                    "storey_id": storey.id() if storey is not None else None,
                    "recommendation": rec,
                    "viswalk_mapping": mapping,
                    "simulation_role": role,
                }
            )

    storey_rows = []

    for storey in sorted(
        storeys,
        key=lambda x: (
            getattr(x, "Elevation", None)
            if getattr(x, "Elevation", None) is not None
            else 0.0
        ),
    ):
        elevation = getattr(storey, "Elevation", None)
        storey_rows.append(
            {
                "entity_id": storey.id(),
                "global_id": global_id(storey),
                "name": entity_name(storey, f"Storey #{storey.id()}"),
                "elevation_project_units": float(elevation) if elevation is not None else None,
                "elevation_m": float(elevation) * unit_scale if elevation is not None else None,
                "counts": dict(storey_counts.get(storey.id(), {})),
                "simulation_mesh_count": int(storey_mesh_counts.get(storey.id(), 0)),
            }
        )

    category_rows = []
    for ifc_type, count in class_counts.most_common():
        sample = next(iter(model.by_type(ifc_type)), None)
        if sample is not None:
            rec, mapping, role = recommendation(sample)
        else:
            rec, mapping, role = "review", "No simulation rule yet", "review"

        category_rows.append(
            {
                "ifc_type": ifc_type,
                "count": count,
                "recommendation": rec,
                "viswalk_mapping": mapping,
                "simulation_role": role,
            }
        )

    warnings = []
    if not storeys:
        warnings.append("No IfcBuildingStorey found; level mapping requires manual review.")
    if unit_entity is None:
        warnings.append("No project LENGTHUNIT found; geometry scale requires review.")
    if proxy_count:
        warnings.append(
            f"{proxy_count} IfcBuildingElementProxy object(s) found; classification may require review."
        )
    if no_storey_count:
        warnings.append(f"{no_storey_count} product(s) are not directly resolved to a storey.")
    if len(products) > 50000:
        warnings.append(
            "Large IFC (>50,000 products): use filtered geometry extraction and cache before full 3D display."
        )

    opening_count = len(model.by_type("IfcOpeningElement"))
    door_count = len(model.by_type("IfcDoor"))
    window_count = len(model.by_type("IfcWindow"))
    fills_count = len(model.by_type("IfcRelFillsElement"))
    voids_count = len(model.by_type("IfcRelVoidsElement"))
    fill_breakdown = _opening_fill_breakdown(model)

    if door_count and fill_breakdown.get("door", 0) < door_count:
        warnings.append(
            f"Doors={door_count} but door-filled openings={fill_breakdown.get('door', 0)}; "
            "some doors may not be linked to openings."
        )

    file_size_bytes = int(path.stat().st_size)
    file_size_mb = file_size_bytes / (1024 * 1024)
    storey_count = len(storeys)
    product_count = len(products)

    wall_count = sum(
        count for ifc_type, count in class_counts.items()
        if ifc_type in {"IfcWall", "IfcWallStandardCase"}
    )
    slab_count = int(class_counts.get("IfcSlab", 0))
    column_count = int(class_counts.get("IfcColumn", 0))
    beam_count = int(class_counts.get("IfcBeam", 0))
    stair_count = int(class_counts.get("IfcStair", 0))
    stair_flight_count = int(class_counts.get("IfcStairFlight", 0))
    ramp_count = int(class_counts.get("IfcRamp", 0)) + int(class_counts.get("IfcRampFlight", 0))
    transport_count = int(class_counts.get("IfcTransportElement", 0))

    large_reasons = []
    if file_size_mb >= 25:
        large_reasons.append(f"file size {file_size_mb:.1f} MB")
    if storey_count >= 20:
        large_reasons.append(f"{storey_count} building storeys")
    if product_count >= 10000:
        large_reasons.append(f"{product_count} IFC products")
    if slab_count >= 500:
        large_reasons.append(f"{slab_count} slab panels")

    large_model = bool(large_reasons)
    structural_like = (
        beam_count > 0
        and slab_count > 0
        and column_count > 0
        and door_count == 0
        and window_count == 0
    )

    if large_model:
        warnings.append(
            "Large Model Mode recommended: " + ", ".join(large_reasons) + "."
        )
    if structural_like:
        warnings.append(
            "This IFC appears structural-heavy and contains no IfcDoor/IfcWindow. "
            "Pedestrian openings may require an architectural IFC or manual review."
        )
    elif door_count == 0:
        warnings.append(
            "No IfcDoor objects were found. Pedestrian openings will not be inferred automatically."
        )

    return {
        "kind": "ifc",
        "status": "audited",
        "source_file": str(path),
        "schema": str(model.schema),
        "project": {
            "name": entity_name(project, "Unnamed IFC Project") if project is not None else None,
            "global_id": global_id(project) if project is not None else None,
        },
        "units": {
            "length_symbol": unit_symbol,
            "scale_to_meters": unit_scale,
        },
        "spatial": {
            "sites": len(sites),
            "buildings": len(buildings),
            "storeys": storey_rows,
        },
        "counts": {
            "products": len(products),
            "doors": door_count,
            "windows": window_count,
            "openings": opening_count,
            "rel_fills": fills_count,
            "rel_voids": voids_count,
            "include": int(recommendation_counts["include"]),
            "review": int(recommendation_counts["review"]),
            "exclude": int(recommendation_counts["exclude"]),
        },
        "opening_fill_breakdown": fill_breakdown,
        "categories": category_rows,
        "elements_preview": element_rows,
        "elements_preview_truncated": len(products) > len(element_rows),
        "large_model": {
            "detected": large_model,
            "reasons": large_reasons,
            "file_size_bytes": file_size_bytes,
            "file_size_mb": round(file_size_mb, 2),
            "recommended_load_mode": "simulation_storey" if large_model else "simulation_all",
            "structural_like": structural_like,
            "simulation_counts": {
                "walls": wall_count,
                "slabs": slab_count,
                "columns": column_count,
                "beams_excluded": beam_count,
                "stairs": stair_count,
                "stair_flights": stair_flight_count,
                "ramps": ramp_count,
                "transport_elements": transport_count,
                "doors": door_count,
                "windows": window_count,
            },
        },
        "warnings": warnings,
        "next_stage": (
            "Large Model Mode: load simulation-relevant/current-storey geometry, "
            "then generate consolidated semantic walkable surfaces."
            if large_model
            else "Filtered 3D extraction + GlobalId selection + simulation preview."
        ),
    }
