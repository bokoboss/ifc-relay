# Viswalk BIM Builder - Real IFC check (dry run, no Vissim)

**Overall: WARN** · generated 2026-10-18T17:46:20 · total <1 s

> ผ่านการตรวจ Geometry (Geometry Engine validation) ไม่ได้หมายความว่าผ่านการตรวจความถูกต้องใน Viswalk ต้องสร้างไฟล์ .inpx และตรวจใน Vissim/Viswalk โดยวิศวกรก่อนนำไปใช้งาน
>
> Passing the Geometry Engine validation does NOT mean the model is correct in Viswalk. Build the .inpx and have an engineer check it in Vissim/Viswalk before use.

## Steps

| Step | Result | Seconds | Detail |
| --- | --- | --- | --- |
| Environment (Python packages, Geometry Engine) | **PASS** | 0.16 | Python 3.13.16, ifcopenshell 0.9.0, engine found |
| Import source IFC (read-only) | **PASS** | 0.0 | 0.0 MB, opened read-only |
| IFC audit | **PASS** | 0.02 | 2 storeys, 3 walls, 5 slabs, 2 stairs / 4 flights |
| Geometry extraction (simulation-relevant) | **PASS** | 0.07 | 12 of 12 elements meshed, 0 failures, 252 triangles |
| Semantic conversion (pedestrian model) | **WARN** | 0.01 | 3 areas, 1 wall segments, 4 vertical connections, 0 not converted, 2 warnings |
| Geometry Engine validation | **PASS** | 0.18 | errors=0 warnings=0 info=0; 6 Vissim obstacles |
| Source IFC unchanged | **PASS** | 0.0 | SHA-256 identical before and after |

## Source

- File: `demo_building.ifc` (0.01 MB)
- SHA-256: `cac170c5b9c744f2de06b276053526d060a56c4c37c88725c80d1d9375b30c08`
- Unchanged after run: True

## IFC content

Schema IFC4 · length unit mm (x0.001 to m) · 19 products · large model: False

| Element | Count |
| --- | --- |
| storeys | 2 |
| slabs | 5 |
| walls | 3 |
| doors | 0 |
| windows | 0 |
| openings | 1 |
| columns | 0 |
| beams | 0 |
| stairs | 2 |
| stair_flights | 4 |
| ramps | 0 |
| ramp_flights | 0 |
| railings | 0 |
| transport_elements | 0 |
| spaces | 0 |
| proxies | 0 |

Default mapping rules: include 10 · review 6 · exclude 3

### Storeys

| Storey | Elevation (m) | Simulation meshes |
| --- | --- | --- |
| L1 | 0.0 | 9 |
| L2 | 3.4 | 3 |

### Audit warnings

- No IfcDoor objects were found. Pedestrian openings will not be inferred automatically.

## Geometry extraction

12 of 12 candidate elements meshed · 0 failures · 252 triangles

## Pedestrian model (semantic conversion)

Stairs: include all IfcStair/IfcStairFlight/IfcRamp/IfcRampFlight (dry-run default)

| Converted | Count |
| --- | --- |
| levels | 2 |
| generated_landing_levels | 1 |
| walkable_areas | 3 |
| obstacles_total | 6 |
| wall_segments | 1 |
| polygon_walls | 2 |
| columns | 0 |
| other_obstacles | 5 |
| void_masks | 2 |
| vertical_connections | 4 |
| vertical_ends_with_offset | 1 |
| door_openings_applied | 0 |
| unfilled_openings | 1 |
| unfilled_passage_candidates | 1 |

### Needs engineering review

| Reason | Count |
| --- | --- |
| ช่องเปิดไม่มีประตูที่ดูเหมือนทางเดิน (ยังปิดไว้) | 1 |
| ปลายบันไดไม่ตรงกับระดับชั้น (ใช้ z offset) | 1 |

### Vertical connections

| Key | Type | Levels | Offsets (m) | Rise (m) | Steps | Level match |
| --- | --- | --- | --- | --- | --- | --- |
| 2001 | stairway | 1 -> 2 | +0.00 / +0.00 | 3.4 | 20 | exact/exact |
| 2002 | stairway | 901 -> 2 | +0.00 / +0.00 | 1.7 | 10 | exact/exact |
| 2003 | stairway | 1 -> 901 | +0.00 / +0.00 | 1.7 | 10 | exact/exact |
| 2004 | stairway | 1 -> 2 | +0.00 / -2.20 | 1.2 | 7 | exact/offset |

Stair direction is derived from geometry and is **not certified** until checked in Vissim.

### All semantic warnings (2)

- 1 wall opening(s) without a door look walkable (sill <= 0.30 m, height >= 1.80 m, width >= 0.60 m) but are kept closed. Review them under Opening candidates and include the ones that are real passages.
- Vertical element IfcStairFlight 3L8IDPHyb01v0xR5FE11dX: top at z=1.200 m matches no storey or landing level within 0.25 m; z offset used. Verify connection in Vissim.

## Geometry Engine validation

Engine v0.3 · build allowed: True · errors 0 · warnings 0 · info 0

| Engine model | Count |
| --- | --- |
| levels | 3 |
| areas | 3 |
| semantic_obstacles | 6 |
| vissim_obstacles | 6 |
| vertical_connections | 4 |

## Environment

Python 3.13.16 · ifcopenshell 0.9.0 · shapely 2.2.0 · engine found True · Vissim required: no · base_empty.inpx required: no

---
Unredacted intermediate files (semantic JSON, engine validation) are in `_private/` next to this report and must not be shared.
