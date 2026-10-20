# Engineering gate before building the Viswalk file

The Geometry Engine refuses only geometry it cannot build. The gate (`gate_service.py`, policy version 2026-10-20) decides what else must be fixed or acknowledged first. It runs on the current pedestrian model and the latest Engine validation; the build endpoint re-validates and re-evaluates it before starting Vissim.

| Item | Policy | Why |
| --- | --- | --- |
| Model not validated | **block** | Validation must run on the current model |
| Engine errors / build not allowed | **block** | The Engine cannot build it |
| Stair/ramp end not on a walkable area (Engine) | **block** | Viswalk cannot use that ramp |
| Stair end reaches no free walking space (connectivity) | ack | Blocked by a wall or no floor; people cannot use it |
| Walking zones not reachable from the main network | ack | Missing door/stair, or a closed room/shaft |
| Stair up-direction not derivable from geometry | ack | Check the direction in Vissim |
| Stair ends using a z offset | ack | Check the connection in Vissim |
| Far off-level slabs left out of the floor | ack | Confirm they are not walkable (sunscreen, canopy) |
| Doors that could not become openings | ack | The wall stays closed there |
| Walkable-looking openings still closed | ack | Open real passages or confirm |
| Multi-storey wall copies without door gaps | ack | Upper storeys may need doors |
| Obstacles with (almost) no floor under them | ack | Wrong level or missing slab |
| Obstacles across the floor edge | info | Walls/columns on the slab edge |
| Overlapping obstacles | info | Joined walls; no effect on walking |

An acknowledgement stores the item count, an optional reason and a timestamp. If a regenerated model changes the count, the item must be acknowledged again. A new IFC import clears all acknowledgements.

Every successful build writes `<name>_build_manifest.json` next to the `.inpx`: source IFC name and SHA-256, Engine severity counts, the full gate result with acknowledgements and reasons, and `viswalk_verified: false` - the model is not verified until an engineer checks it in Viswalk.
