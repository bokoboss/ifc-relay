# Vertical Circulation (semantic schema 0.6.1, P0)

> Status: **P0 is locally tested, including IFC2X3/IFC4 synthetic fixtures. The P0 changes have not been verified through Vissim COM or pedestrian simulation.** The Vissim results below are historical checks of the earlier converter, not qualification of P0.
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
5. **Physical landing planes.** Heights use a separate **0.00001 m** numerical tolerance anchored to a source height, without transitive clustering or height averaging. A landing at any existing storey walking datum contributes to that storey's Area; other heights get generated levels (`key` 901+, `generated: true`) at their actual world Z. Every candidate receives one assignment. Non-landing off-level slab review thresholds remain unchanged.
6. **Endpoint matching.** Each true flight edge must contact a local source walking surface (5 mm XY/height precision allowance). Known, conflicting stair parents are rejected. Differences up to **0.25 m** can be compensated only with evidence: the related landing slab's measured underside, or the flight's own IFC `RiserHeight` matching one riser in metres. These are `surface_adjusted` / `riser_adjusted`, not `exact`. Unsupported ends keep explicit offsets and structured `stair_endpoint_unresolved` diagnostics; a level reference is not a connectivity link. No landing is created from a gap.
7. **Steps.** The flight's own `NumberOfRisers` (`NumberOfRiser` in IFC2x3); otherwise `round(rise / 0.17)`. A parent stair's riser count is never reused for a single flight. `steps_source` records which one was used.

Checks that produce warnings rather than silent results: non-straight flight footprints (footprint < 85 % of its rectangle), rise < 0.05 m, both ends on the same level, unmatched ends, included elevators/escalators (`IfcTransportElement`, still exported only as an obstacle).

## Record format

Existing engine fields are unchanged (`key, name, type, start_level, end_level, start_z_offset, end_z_offset, polygon, thickness, show_balustrade, steps`). Added traceability fields: `ifc_parent_global_id, geometry_source, polygon_order, bottom_edge, top_edge, z_bottom, z_top, rise, run_length, width, level_match, steps_source`.

P0 adds `endpoint_support` (per-end source Z, supporting surface identity/Z, contact length, compensation reason or unresolved reason) and `ifc_semantic.landing_ledger`. Each source landing has one outcome: `represented`, `contributed_to_existing_area`, `excluded`, or `unresolved`. Components retain their source outline/holes and map to final Area keys, intersection areas and coverage. A GlobalId listed on another region is not counted as represented. Reconciliation happens after manual edits and final key allocation, with void masks removed from output coverage.

`summary.source_landings`, `landings_represented` (including contributions to existing Areas), `landings_contributed_to_existing`, `landings_excluded`, `landings_review` and `landings_omitted` count source objects independently of `landing_areas` and `generated_landing_levels`. In P0, unresolved source outcomes count as both review and omitted/incomplete; an explicit exclusion is neither. Geometry validity (unknown before Engine validation), geometry-only connectivity and `viswalk_verified: false` are separate statuses.

Landing consolidation uses actual source geometry without gap filling. Floor slab joint closing remains enabled, runs in floating precision and accepts a repair only if every source component remains covered. Landing holes generate void-mask obstacles, including small holes. Small landing zones are retained by connectivity when they support an evidenced flight endpoint. Connectivity and Engine validation check final ramp-end strips; nearby unrelated floors or overlap in the middle of a ramp do not establish a connection.

## Engine contract (checked against `05_geometry_engine_v03.py`, validate-only)

| Question | Finding | Handling |
| --- | --- | --- |
| Extra fields / level keys 901+ | Ignored / accepted (keys only need to be > 0 and unique) | none needed |
| `start_z_offset` / `end_z_offset` | Passed to Vissim as `StartZOffset` / `EndZOffset` | used for ends that match no level |
| `start_level == end_level` | **Rejected** (`ValueError`) | an end between levels is referenced to the nearest *other* level (above, negative offset) |
| Ramp end must overlap the area of its level | Engine validation warns when a ramp only touches it | polygon extended by 0.10 m only at ends whose level area does not already lie under the end (stair wells count as no floor); `end_overlap` records `{bottom, top}`; `bottom_edge`/`top_edge` keep the true flight edges |
| Low end of a stairway | Engine passes the polygon WKT unchanged to `Ramps.AddRamp`; direction comes from Vissim's reading of the polygon | records are bottom edge first; **confirm in Vissim** which edge it treats as the start |

Engine-contract tests (`tests/test_engine_contract_*.py`) use `project_paths.engine_path()` (environment/local override or bundled engine) and skip only when that file is absent. Validation does not activate COM.

## Verified in Vissim 2025 (SP 15), 2026-10-20

Revit advanced sample (5 storeys, 10 stairs / 20 flights, two generated landing levels) built through COM and opened in Vissim:

- All 20 ramps `STAIRWAY`, levels `1 -> 901 -> 2 -> 902 -> 3`, offsets 0, `rise x steps` = 1.90 m.
- Vissim keeps our first point (bottom edge) as the ramp start; the first stored edge runs bottom -> top for flights rising in +y and in -y. Stair direction checked visually by the engineer: correct.
- Both ends of every ramp touch the walkable area of their own level.
- The 0.10 m extension at both ends made that run 0.20 m longer than the IFC flight (going 0.348 m instead of 0.330 m). Since 2026-10-20 an end standing on its floor is not extended (Revit sample: 7 of 20 flights keep their bottom end exact).
- Vissim stores `usableWid` 0.58 m for a 1.14 m flight. In the Vissim 2024 manual *Usable width (UsableWid)* is the escalator/moving-walkway step width ("value range 600 to 1,200 mm", basis of the socket width); a `STAIRWAY` is defined by its polygon width, so the 0.58 m default does not narrow the stair. No change made.

## Still to verify in Vissim

- Negative `EndZOffset` (ends between levels) - not exercised by the Revit sample.
- Pedestrian routing L1 -> landing -> L2 in a simulation run.

## Walkable continuity (no gaps)

Vissim connects walkable elements only "at the points where they directly touch or overlap" and groups touching/overlapping areas into one walkable polygon (Vissim 2025 manual, *Modeling construction elements*). A gap, however small, splits the walking ground. The converter therefore:

- closes gaps narrower than 50 mm between floor slabs of one level (morphological closing; outer edges unchanged) and reports how many it closed;
- adds manual walkable floor drawn on the plan as drawn, overlapping the existing floor, instead of a cut-to-fit piece that would only touch along a seam;
- makes every ramp end overlap its level's area: by at least 0.09 m where the floor already lies under the end, otherwise by extending the ramp 0.10 m (stair wells count as no floor);
- reports any remaining separate walking zones in the connectivity check.
