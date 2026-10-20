# Before the build: what stops it, what to check in Viswalk

This app converts IFC into a Viswalk model; it is **not a BIM checker**. Anything the engineer can fix in Viswalk after the build is listed, not enforced (`gate_service.py`, policy version 2026-10-21.1). The build endpoint re-validates and re-evaluates the list before starting Vissim.

| Item | Policy | Why |
| --- | --- | --- |
| Engine errors / build not allowed | **block** | The Engine cannot build the file |
| Stair/ramp end not on a walkable area (Engine) | check | Viswalk will error at that ramp; connect it to an Area in Viswalk |
| Connectivity diagnostic failed or missing | check | Listed, never read as "all connected"; does not affect the file |
| Manual plan edit that could not be applied | check | The file will not contain it; redraw it or fix in Viswalk |
| Stair end reaches no free walking space (connectivity) | check | Blocked by a wall or no floor; people cannot use it |
| Walking zones not reachable from the main network | check | Missing door/stair, or a closed room/shaft |
| Stair up-direction not derivable from geometry | check | Check the direction in Vissim |
| Stair ends using a z offset | check | Check the connection in Vissim |
| Far off-level slabs left out of the floor | check | Usually sunscreens/canopies; include them if walkable |
| Doors that could not become openings | check | The wall stays closed there |
| Walkable-looking openings still closed | check | Open real passages in the app or in Viswalk |
| Multi-storey wall copies without door gaps | check | Upper storeys may need doors |
| Obstacles with (almost) no floor under them | check | Wrong level or missing slab |
| Obstacles across the floor edge | info | Walls/columns on the slab edge |
| Overlapping obstacles | info | Usually joined walls; many overlaps can mean duplicates - check in the plan |

With check items present, Build asks for one confirmation listing them; nothing has to be ticked. Each item carries a **fingerprint** (policy version + the identities of the problems: IFC GlobalIds, zone level/location/area, edit ids), so the manifest records exactly which problems were known at build time.

The connectivity check is a geometry-only diagnostic (free walking space touching); it is not routing verification and says nothing about origins, exits or clear widths.

Plan edits are listed with what the last pedestrian-model run did with each one: `ใช้แล้ว` (applied as drawn), `ย้ายระดับ` (its level was renumbered and it was re-bound by height), `ไม่มีผล` (a passage that crossed no wall), `ใช้ไม่ได้` (skipped; listed as a Viswalk check) and `รอเตรียมใหม่` (added since the last run). The list header counts the edits that need a look, so after an IFC revision the engineer works through it as a review queue.

Every successful build writes next to the `.inpx`:

- `<name>_viswalk_checklist.md` - the check items as a tick list (title, count, detail, object ids), for the review in Viswalk.
- `<name>_build_manifest.json` - source IFC name and SHA-256, pedestrian-model file SHA-256, output `.inpx` SHA-256, Geometry Engine file SHA-256, Vissim release used, manual edits with apply status, Engine severity counts, the full list with fingerprints (`engineering_gate`, `check_in_viswalk`) and `viswalk_verified: false` - the model is not verified until an engineer checks it in Viswalk.

## Manual plan edits

Edits drawn in the 2D plan (`manual_edits.py`: added walkable floor, added obstacle, passage through walls) are stored in the project state, never in the IFC, and re-applied every time the pedestrian model is generated. They appear in the list as an `info` item and in the build manifest via the semantic model (`ifc_semantic.manual_edits`). They carry over to a new IFC revision when "keep selections" is on.
