# Checks

Numbered regression scripts from earlier versions. Run from the repository root, e.g. `python checks/42_check_walkable_merge_v041.py`.

| Script | Needs | In CI |
| --- | --- | --- |
| 34 Three.js dependency, 38 export UI, 42 walkable merge, 44 static UI | nothing | 38, 42, 44 |
| 35 static URLs (PowerShell) | running app on port 8765 | no |
| 36 Fixture #1 semantic | `TallBuilding.ifc` (`VBB_FIXTURE1_IFC`), run by `verify_vissim.bat` | no |
| 41, 43, 45, 46 large IFC | large project IFC via `VBB_LARGE_IFC` | no |

Project IFC files are never committed. New tests go in `tests/` (pytest, synthetic IFC).
