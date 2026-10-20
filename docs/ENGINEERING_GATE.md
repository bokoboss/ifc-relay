# Engineering gate before building the Viswalk file

The Geometry Engine refuses only geometry it cannot build. The gate (`gate_service.py`, policy version 2026-10-20.2) decides what else must be fixed or acknowledged first. It runs on the current pedestrian model and the latest Engine validation; the build endpoint re-validates and re-evaluates it before starting Vissim.

| Item | Policy | Why |
| --- | --- | --- |
| Model not validated | **block** | Validation must run on the current model |
| Engine errors / build not allowed | **block** | The Engine cannot build it |
| Stair/ramp end not on a walkable area (Engine) | **block** | Viswalk cannot use that ramp |
| Connectivity diagnostic failed or missing | **block** | Never read a failed check as "all connected" |
| Manual plan edit that could not be applied | **block** | The engineer drew it; the model does not contain it |
| Stair end reaches no free walking space (connectivity) | ack, **reason required** | Blocked by a wall or no floor; people cannot use it |
| Walking zones not reachable from the main network | ack, **reason required** | Missing door/stair, or a closed room/shaft |
| Stair up-direction not derivable from geometry | ack | Check the direction in Vissim |
| Stair ends using a z offset | ack | Check the connection in Vissim |
| Far off-level slabs left out of the floor | ack | Confirm they are not walkable (sunscreen, canopy) |
| Doors that could not become openings | ack | The wall stays closed there |
| Walkable-looking openings still closed | ack | Open real passages or confirm |
| Multi-storey wall copies without door gaps | ack | Upper storeys may need doors |
| Obstacles with (almost) no floor under them | ack | Wrong level or missing slab |
| Obstacles across the floor edge | info | Walls/columns on the slab edge |
| Overlapping obstacles | info | Usually joined walls; many overlaps can mean duplicates - check in the plan |

An acknowledgement stores the item's **fingerprint** (policy version + the identities of the problems: IFC GlobalIds, zone level/location/area, edit ids), the reason and a timestamp. If a regenerated model has a different set of problems - even with the same count - the item must be acknowledged again. A new IFC import clears all acknowledgements.

The connectivity check is a geometry-only diagnostic (free walking space touching); it is not routing verification and says nothing about origins, exits or clear widths.

Plan edits are listed with what the last pedestrian-model run did with each one: `ใช้แล้ว` (applied as drawn), `ย้ายระดับ` (its level was renumbered and it was re-bound by height), `ไม่มีผล` (a passage that crossed no wall), `ใช้ไม่ได้` (skipped; blocks the build) and `รอเตรียมใหม่` (added since the last run). The list header counts the edits that need a look, so after an IFC revision the engineer works through it as a review queue.

Every successful build writes `<name>_build_manifest.json` next to the `.inpx`: source IFC name and SHA-256, pedestrian-model file SHA-256, output `.inpx` SHA-256, Geometry Engine file SHA-256, manual edits with apply status, Engine severity counts, the full gate result with fingerprints, acknowledgements and reasons, and `viswalk_verified: false` - the model is not verified until an engineer checks it in Viswalk.

## Manual plan edits

Edits drawn in the 2D plan (`manual_edits.py`: added walkable floor, added obstacle, passage through walls) are stored in the project state, never in the IFC, and re-applied every time the pedestrian model is generated. They appear in the gate as an `info` item and in the build manifest via the semantic model (`ifc_semantic.manual_edits`). They carry over to a new IFC revision when "keep selections" is on.
