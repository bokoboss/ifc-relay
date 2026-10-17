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

## To verify on Windows / Vissim (engine is outside this repo)

| # | Question for `05_geometry_engine_v03.py` | Why it matters |
| --- | --- | --- |
| 1 | Does it accept extra level/area/connection fields and level keys 901+? | Generated landing levels |
| 2 | Does it apply `start_z_offset` / `end_z_offset`? | Unmatched ends |
| 3 | How does it decide the low end of a stairway polygon? | Records are now bottom edge first; the engine may need to read `polygon_order` or `bottom_edge` |
| 4 | Does it accept `start_level == end_level` with different offsets? | Partial flights |
| 5 | Does the Vissim build place Areas on generated levels correctly? | Landing areas |

Suggested acceptance: a two-storey IFC with one straight stair and one U-stair builds, reopens in Vissim, and pedestrians can route L1 → landing → L2.
