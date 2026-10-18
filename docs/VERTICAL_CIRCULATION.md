# Vertical Circulation (v0.5 draft)

> Status: **implemented in the semantic layer, unit/synthetic-IFC tested, not yet verified in Vissim.**
> Stairs and ramps remain review-only by default. Nothing changes for an IFC unless the engineer includes a stair, ramp or flight.

## Problem in v0.4.1a

- Each included stair/ramp was connected from its storey to the *next* storey, whatever its real height.
- The whole footprint of an `IfcStair` was used, so U-shaped stairs became one large rectangle with no direction.
- An `IfcStair` without its own representation (common in Revit exports, where geometry lives on the flights) produced only a "no cached mesh" warning.
- Landing slabs between storeys were merged into the storey floor area at the wrong height.

## Method

1. **Units.** An included `IfcStair`/`IfcRamp` is decomposed into its `IfcStairFlight`/`IfcRampFlight` children that have geometry. A child explicitly set to *Exclude* is skipped. If the parent has no meshable children, the parent mesh is used. An included flight whose parent was not included is converted on its own.
2. **Flight profile** (`ifc_vertical_service.flight_profile`). From the cached mesh: XY footprint → minimum rotated rectangle → long axis = run direction. The highest vertex near each end decides which end is low. Output polygon is the oriented rectangle, **bottom edge first** (`polygon_order: "bottom_edge_first"`).
3. **Heights.** `z_bottom` / `z_top` are the mesh minimum / maximum.
4. **Walking datum per storey.** Median top of the storey's included non-landing slabs. If it differs from `IfcBuildingStorey.Elevation` by more than 0.05 m, a warning is raised. Output level `z` stays the storey elevation (regression-stable).
5. **Intermediate landings.** A landing slab (`PredefinedType=LANDING`, or a slab aggregated under a stair/ramp) whose top is more than 0.25 m from its storey datum becomes a **generated level** (`key` 901+, `generated: true`) with its own Area. Landings within 0.25 m of each other share one level.
6. **Level matching.** Each flight end snaps to the nearest storey datum or landing level within **0.25 m** (larger than one riser, so a Revit run that ends one riser below the landing still matches). An end that matches nothing keeps an explicit `start_z_offset`/`end_z_offset` relative to the level below and raises a warning.
7. **Steps.** The flight's own `NumberOfRisers` (`NumberOfRiser` in IFC2x3); otherwise `round(rise / 0.17)`. A parent stair's riser count is never reused for a single flight. `steps_source` records which one was used.

Checks that produce warnings rather than silent results: non-straight flight footprints (footprint < 85 % of its rectangle), rise < 0.05 m, both ends on the same level, unmatched ends, included elevators/escalators (`IfcTransportElement`, still exported only as an obstacle).

## Record format

Existing engine fields are unchanged (`key, name, type, start_level, end_level, start_z_offset, end_z_offset, polygon, thickness, show_balustrade, steps`). Added traceability fields: `ifc_parent_global_id, geometry_source, polygon_order, bottom_edge, top_edge, z_bottom, z_top, rise, run_length, width, level_match, steps_source`.

## Engine contract (checked against `05_geometry_engine_v03.py`, validate-only)

| Question | Finding | Handling |
| --- | --- | --- |
| Extra fields / level keys 901+ | Ignored / accepted (keys only need to be > 0 and unique) | none needed |
| `start_z_offset` / `end_z_offset` | Passed to Vissim as `StartZOffset` / `EndZOffset` | used for ends that match no level |
| `start_level == end_level` | **Rejected** (`ValueError`) | an end between levels is referenced to the nearest *other* level (above, negative offset) |
| Ramp end must overlap the area of its level | Engine validation warns when a ramp only touches it | polygon extended by `end_overlap` = 0.10 m beyond both ends; `bottom_edge`/`top_edge` keep the true flight edges |
| Low end of a stairway | Engine passes the polygon WKT unchanged to `Ramps.AddRamp`; direction comes from Vissim's reading of the polygon | records are bottom edge first; **confirm in Vissim** which edge it treats as the start |

Engine-contract tests (`tests/test_engine_contract_*.py`) run the real engine when `VBB_GEOMETRY_ENGINE` points to a local copy, and are skipped otherwise.

## Still to verify in Vissim

- Which polygon edge Vissim treats as the ramp start, and that negative `EndZOffset` is accepted.
- A two-storey IFC with one straight stair and one U-stair builds, reopens, and pedestrians route L1 → landing → L2.
