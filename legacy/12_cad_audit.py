import json
from collections import Counter, defaultdict
from pathlib import Path

import ezdxf
from ezdxf import units


PROJECT_DIR = Path(__file__).resolve().parent
DXF_FILE = PROJECT_DIR / "sample_floorplan.dxf"
CONFIG_FILE = PROJECT_DIR / "cad_layer_mapping.json"
REPORT_FILE = PROJECT_DIR / "output" / "cad_audit_report.json"


UNIT_NAMES = {
    0: "unitless",
    1: "in",
    2: "ft",
    3: "mi",
    4: "mm",
    5: "cm",
    6: "m",
    7: "km",
}


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def detect_scale_to_meters(doc, config):
    override = config.get("source_units_override")

    manual = {
        "m": 1.0,
        "cm": 0.01,
        "mm": 0.001,
        "km": 1000.0,
        "in": 0.0254,
        "ft": 0.3048,
    }

    if override:
        key = str(override).lower().strip()
        if key not in manual:
            raise ValueError(
                f"Unsupported source_units_override: {override}"
            )
        return manual[key], f"override:{key}"

    source_units = int(doc.units or 0)

    if source_units == 0:
        return (
            float(config.get("unitless_scale_to_meters", 1.0)),
            "DXF unitless + configured scale",
        )

    try:
        factor = float(
            units.conversion_factor(source_units, units.M)
        )
        return factor, f"$INSUNITS={source_units}"
    except Exception:
        return (
            float(config.get("unitless_scale_to_meters", 1.0)),
            f"unsupported $INSUNITS={source_units}; fallback configured scale",
        )


def main():
    if not DXF_FILE.exists():
        raise FileNotFoundError(f"DXF not found: {DXF_FILE}")
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config not found: {CONFIG_FILE}")

    config = load_json(CONFIG_FILE)
    doc = ezdxf.readfile(DXF_FILE)
    msp = doc.modelspace()

    scale, scale_basis = detect_scale_to_meters(doc, config)

    type_counts = Counter()
    layer_counts = Counter()
    layer_type_counts = defaultdict(Counter)
    inserts = []
    polylines_with_arcs = []
    unsupported_3d = []
    suspicious = []

    for entity in msp:
        etype = entity.dxftype()
        layer = str(entity.dxf.get("layer", "0"))
        type_counts[etype] += 1
        layer_counts[layer] += 1
        layer_type_counts[layer][etype] += 1

        if etype == "INSERT":
            inserts.append({
                "block_name": str(entity.dxf.name),
                "layer": layer,
                "insert": [
                    float(entity.dxf.insert.x),
                    float(entity.dxf.insert.y),
                    float(entity.dxf.insert.z),
                ],
                "rotation_deg": float(entity.dxf.get("rotation", 0.0)),
                "xscale": float(entity.dxf.get("xscale", 1.0)),
                "yscale": float(entity.dxf.get("yscale", 1.0)),
                "mcount": int(getattr(entity, "mcount", 1)),
            })

        if etype == "LWPOLYLINE":
            if bool(getattr(entity, "has_arc", False)):
                polylines_with_arcs.append({
                    "handle": entity.dxf.handle,
                    "layer": layer,
                    "entity_type": etype,
                })

        if etype == "POLYLINE":
            # Old POLYLINE may represent 2D, 3D, mesh or polyface.
            if bool(getattr(entity, "is_3d_polyline", False)):
                unsupported_3d.append({
                    "handle": entity.dxf.handle,
                    "layer": layer,
                    "entity_type": etype,
                    "reason": "3D POLYLINE needs explicit projection policy",
                })

        if etype in {"3DFACE", "MESH", "POLYFACE"}:
            unsupported_3d.append({
                "handle": entity.dxf.handle,
                "layer": layer,
                "entity_type": etype,
                "reason": "3D geometry not consumed by 2D floor-plan parser",
            })

    # Layer-rule coverage is reported conservatively by exact aliases and regex.
    import re
    mapped_layers = {}
    unmapped_layers = []

    rules = config.get("layer_rules", [])

    for layer in sorted(layer_counts):
        matched = None
        for rule in rules:
            aliases = {
                str(x).upper()
                for x in rule.get("aliases", [])
            }
            if layer.upper() in aliases:
                matched = rule["semantic"]
                break
            regex = rule.get("regex")
            if regex and re.match(regex, layer, flags=re.IGNORECASE):
                matched = rule["semantic"]
                break

        if matched:
            mapped_layers[layer] = matched
        elif layer != "0":
            unmapped_layers.append(layer)

    source_units = int(doc.units or 0)

    report = {
        "source_file": str(DXF_FILE),
        "dxf_version": str(doc.dxfversion),
        "insunits_code": source_units,
        "insunits_name": UNIT_NAMES.get(source_units, f"code:{source_units}"),
        "scale_to_meters": scale,
        "scale_basis": scale_basis,
        "entity_count": sum(type_counts.values()),
        "entity_types": dict(sorted(type_counts.items())),
        "layers": {
            layer: {
                "count": layer_counts[layer],
                "entity_types": dict(sorted(layer_type_counts[layer].items())),
                "mapped_semantic": mapped_layers.get(layer),
            }
            for layer in sorted(layer_counts)
        },
        "unmapped_layers": unmapped_layers,
        "inserts": inserts,
        "polylines_with_arc_bulges": polylines_with_arcs,
        "unsupported_3d_entities": unsupported_3d,
        "suspicious": suspicious,
        "audit_status": (
            "REVIEW"
            if unmapped_layers or unsupported_3d
            else "PASS"
        ),
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_FILE.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("Viswalk CAD Audit v0.2")
    print("=" * 60)
    print("Source:", DXF_FILE)
    print("DXF version:", doc.dxfversion)
    print(
        "Units:",
        UNIT_NAMES.get(source_units, source_units),
        f"| scale to m = {scale}",
        f"| {scale_basis}",
    )
    print("Entities:", report["entity_count"])
    print("Layers:", len(layer_counts))
    print("INSERTs:", len(inserts))
    print("Bulged polylines:", len(polylines_with_arcs))
    print("Unsupported 3D:", len(unsupported_3d))
    print("Unmapped layers:", len(unmapped_layers))

    if unmapped_layers:
        print("\nUNMAPPED LAYERS")
        for layer in unmapped_layers:
            print(" -", layer)

    print("\nLayer summary:")
    for layer, info in report["layers"].items():
        print(
            f"  {layer:<24} "
            f"{info['count']:>4} entities "
            f"-> {info['mapped_semantic'] or 'UNMAPPED'}"
        )

    print("\nAudit status:", report["audit_status"])
    print("Report:", REPORT_FILE)


if __name__ == "__main__":
    main()
