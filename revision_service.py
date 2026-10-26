"""Carry engineer review decisions across IFC revisions.

Selection overrides are keyed by IFC GlobalId, which authoring tools keep
stable between exports. When a new revision of the same model is imported,
the previous decisions are re-applied and checked:

* carried   - the GlobalId still exists; the decision is kept.
* orphaned  - the GlobalId no longer exists; the decision is dropped and listed.
* changed   - the element still exists but its class, type, name, storey,
              placement or shape representation changed since the decision
              was made; the decision is kept and listed for re-review.

Only elements with a decision are fingerprinted, so the cost stays small on
large models. Source IFC files are never modified.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ifc_service import _imports, entity_name, global_id, resolve_storey, storey_lookup

REPORT_LIST_LIMIT = 200
_ID_RE = re.compile(r"#\d+")


def _placement_signature(element: Any, unit_scale: float) -> str | None:
    placement = getattr(element, "ObjectPlacement", None)
    if placement is None:
        return None
    try:
        import ifcopenshell.util.placement

        matrix = ifcopenshell.util.placement.get_local_placement(placement)
    except Exception:
        return None
    values = []
    for r in range(3):
        for c in range(4):
            v = float(matrix[r][c]) * (unit_scale if c == 3 else 1.0)
            values.append(f"{round(v, 3):.3f}")
    return ",".join(values)


def _shape_signature(model: Any, element: Any) -> str | None:
    """Hash the representation tree with entity ids removed."""
    product_shape = getattr(element, "Representation", None)
    if product_shape is None:
        return None
    lines: list[str] = []
    for rep in getattr(product_shape, "Representations", None) or []:
        try:
            for item in model.traverse(rep):
                lines.append(_ID_RE.sub("#", str(item)))
        except Exception:
            lines.append(_ID_RE.sub("#", str(rep)))
    lines.sort()
    return hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()


def element_fingerprint(model: Any, element: Any, lookup: dict[int, Any], util_element: Any,
                        unit_scale: float) -> dict[str, Any]:
    storey = resolve_storey(element, lookup, util_element)
    return {
        "ifc_type": str(element.is_a()),
        "predefined_type": str(getattr(element, "PredefinedType", "") or ""),
        "name": entity_name(element, ""),
        "storey": global_id(storey) if storey is not None else None,
        "placement": _placement_signature(element, unit_scale),
        "shape": _shape_signature(model, element),
    }


def _open(path: Path) -> tuple[Any, dict[int, Any], Any, float]:
    ifcopenshell, util_element, util_unit = _imports()
    model = ifcopenshell.open(str(path))
    return model, storey_lookup(model), util_element, float(util_unit.calculate_unit_scale(model))


def _product_guids(model: Any) -> set[str]:
    return {g for g in (global_id(p) for p in model.by_type("IfcProduct")) if g}


def compare_revisions(
    previous_path: Path | None,
    current_path: Path,
    overrides: dict[str, str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return ``(carried_overrides, report)`` for a new IFC revision.

    ``previous_path`` may be missing (e.g. the old upload was deleted); then
    only existence is checked and changes cannot be detected.
    """
    cur_model, cur_lookup, util_element, cur_scale = _open(current_path)
    cur_guids = _product_guids(cur_model)

    prev_model = None
    prev_guids: set[str] | None = None
    if previous_path is not None and previous_path.exists():
        prev_model, prev_lookup, _, prev_scale = _open(previous_path)
        prev_guids = _product_guids(prev_model)

    carried: dict[str, str] = {}
    orphaned: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    for guid, status in sorted(overrides.items()):
        if guid not in cur_guids:
            item: dict[str, Any] = {"global_id": guid, "status": status}
            if prev_model is not None:
                try:
                    old = prev_model.by_guid(guid)
                    item.update(ifc_type=str(old.is_a()), name=entity_name(old, ""))
                except Exception:
                    pass
            orphaned.append(item)
            continue

        carried[guid] = status
        if prev_model is None:
            continue
        try:
            old_el = prev_model.by_guid(guid)
        except Exception:
            continue
        new_el = cur_model.by_guid(guid)
        old_fp = element_fingerprint(prev_model, old_el, prev_lookup, util_element, prev_scale)
        new_fp = element_fingerprint(cur_model, new_el, cur_lookup, util_element, cur_scale)
        diffs = [k for k in old_fp if old_fp[k] != new_fp[k]]
        if diffs:
            changed.append({
                "global_id": guid,
                "status": status,
                "ifc_type": new_fp["ifc_type"],
                "name": new_fp["name"],
                "changes": diffs,
            })

    products: dict[str, Any] = {"current": len(cur_guids)}
    if prev_guids is not None:
        products.update(
            previous=len(prev_guids),
            added=len(cur_guids - prev_guids),
            removed=len(prev_guids - cur_guids),
            kept=len(cur_guids & prev_guids),
        )

    report = {
        "status": "applied",
        "previous_file": previous_path.name if previous_path is not None else None,
        "previous_file_available": prev_model is not None,
        "current_file": current_path.name,
        "products": products,
        "decisions": {
            "previous": len(overrides),
            "carried": len(carried),
            "orphaned": len(orphaned),
            "changed": len(changed),
        },
        "orphaned": orphaned[:REPORT_LIST_LIMIT],
        "changed": changed[:REPORT_LIST_LIMIT],
        "truncated": len(orphaned) > REPORT_LIST_LIMIT or len(changed) > REPORT_LIST_LIMIT,
    }
    return carried, report


def report_messages(report: dict[str, Any]) -> list[str]:
    """Human-readable lines for the audit warning list."""
    d = report["decisions"]
    lines = [
        f"Revision carry-over: {d['carried']} of {d['previous']} review decision(s) re-applied "
        f"from {report.get('previous_file') or 'the previous import'}."
    ]
    p = report.get("products", {})
    if "added" in p:
        lines.append(
            f"Revision diff: {p['added']} product(s) added, {p['removed']} removed, {p['kept']} kept."
        )
    if not report.get("previous_file_available"):
        lines.append("Previous IFC file is no longer available; geometry changes could not be checked.")
    if d["orphaned"]:
        lines.append(
            f"{d['orphaned']} decision(s) dropped because the element no longer exists in this revision."
        )
    if d["changed"]:
        sample = ", ".join(
            f"{c['ifc_type']} {c['name'] or c['global_id']} ({'/'.join(c['changes'])})"
            for c in report["changed"][:5]
        )
        lines.append(
            f"{d['changed']} element(s) with a review decision changed since the last revision; re-check them: {sample}"
            + (" ..." if d["changed"] > 5 else "")
        )
    return lines


# C3 — IFC identity guard for manual edits stored in IFC-local XY coordinates.
# These checks do not claim geometric registration when georeferencing is absent.
def inspect_project_identity(path: Path) -> dict[str, Any]:
    """Read project identity and spatial settings without tessellating geometry."""
    model, _, _, scale = _open(path)

    def entities(name: str) -> list[Any]:
        try:
            return list(model.by_type(name))
        except (RuntimeError, ValueError):
            return []  # e.g. IFC2X3 does not declare IfcMapConversion

    def attrs(obj: Any, names: tuple[str, ...]) -> dict[str, Any]:
        result = {}
        for name in names:
            value = getattr(obj, name, None)
            if value is None:
                result[name] = None
            elif isinstance(value, (int, float, str, bool)):
                result[name] = value
            elif hasattr(value, "wrappedValue"):
                result[name] = str(value.wrappedValue)
            else:
                result[name] = str(value)
        return result

    project = entities("IfcProject")
    guid = str(getattr(project[0], "GlobalId", "") or "") if len(project) == 1 else None

    conversions = [
        attrs(entry, ("Eastings", "Northings", "OrthogonalHeight", "XAxisAbscissa",
                      "XAxisOrdinate", "Scale", "FactorX", "FactorY", "FactorZ"))
        for entry in entities("IfcMapConversion")
    ]
    projected = [
        attrs(entry, ("Name", "GeodeticDatum", "VerticalDatum",
                      "MapProjection", "MapZone"))
        for entry in entities("IfcProjectedCRS")
    ]
    contexts = []
    for entry in entities("IfcGeometricRepresentationContext"):
        wcs = getattr(entry, "WorldCoordinateSystem", None)
        north = getattr(entry, "TrueNorth", None)
        contexts.append({
            "ContextType": getattr(entry, "ContextType", None),
            "CoordinateSpaceDimension": getattr(entry, "CoordinateSpaceDimension", None),
            "Precision": getattr(entry, "Precision", None),
            "wcs_location": list(getattr(getattr(wcs, "Location", None), "Coordinates", []) or []),
            "wcs_axis": list(getattr(getattr(wcs, "Axis", None), "DirectionRatios", []) or []),
            "wcs_ref": list(getattr(getattr(wcs, "RefDirection", None), "DirectionRatios", []) or []),
            "true_north": list(getattr(north, "DirectionRatios", []) or []),
        })
    sites = []
    for entry in entities("IfcSite"):
        sites.append({
            "GlobalId": getattr(entry, "GlobalId", None),
            "RefLatitude": list(getattr(entry, "RefLatitude", []) or []),
            "RefLongitude": list(getattr(entry, "RefLongitude", []) or []),
            "RefElevation": getattr(entry, "RefElevation", None),
        })
    return {
        "project_guid": guid,
        "unit_scale_to_m": scale,
        "schema": str(model.schema),
        "map_conversion": conversions,
        "projected_crs": projected,
        "contexts": contexts,
        "sites": sites,
    }


def compare_project_identity(previous: dict[str, Any] | None,
                             incoming: dict[str, Any]) -> dict[str, Any]:
    """Return verified/mismatch/unverified. Never infer equivalence from GUID alone."""
    if previous is None:
        return {"status": "unverified", "reasons": ["ไม่มี IFC ต้นทางสำหรับเปรียบเทียบ"],
                "previous": None, "incoming": incoming}
    reasons: list[str] = []
    mismatches: list[str] = []
    a, b = previous, incoming
    if not a.get("project_guid") or not b.get("project_guid"):
        reasons.append("ไม่มี IfcProject.GlobalId ที่ตรวจสอบได้")
    elif a["project_guid"] != b["project_guid"]:
        mismatches.append("IfcProject.GlobalId ต่างกัน")
    if a.get("unit_scale_to_m") is None or b.get("unit_scale_to_m") is None:
        reasons.append("ไม่สามารถตรวจหน่วย IFC ได้ครบ")
    elif a["unit_scale_to_m"] != b["unit_scale_to_m"]:
        mismatches.append("หน่วยหรือมาตราส่วน IFC ต่างกัน")
    for field in ("map_conversion", "projected_crs", "contexts", "sites"):
        if a.get(field) != b.get(field):
            mismatches.append(f"ข้อมูลพิกัด/Georeference ต่างกัน: {field}")
    if not a.get("map_conversion") or not b.get("map_conversion"):
        reasons.append("ไม่มี Map Conversion ที่รับรองการอ้างอิงพิกัดของทั้งสอง IFC")
    if not a.get("projected_crs") or not b.get("projected_crs"):
        reasons.append("ไม่มี Projected CRS ที่ตรวจสอบได้ครบ")
    if not a.get("contexts") or not b.get("contexts"):
        reasons.append("ไม่มี Representation Context ที่ตรวจสอบได้ครบ")
    status = "mismatch" if mismatches else "unverified" if reasons else "verified"
    return {"status": status, "reasons": mismatches or reasons,
            "previous": a, "incoming": b}
