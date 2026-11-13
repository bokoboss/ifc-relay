# Checks

Numbered regression scripts from earlier versions. Run from the repository root, e.g. `python checks/42_check_walkable_merge_v041.py`.

| Script | Needs | In CI |
| --- | --- | --- |
| 34 Three.js dependency, 38 export UI, 42 walkable merge, 44 static UI | nothing | 38, 42, 44 |
| 35 static URLs (PowerShell) | running app on port 8765 | no |
| 36 Fixture #1 semantic | `TallBuilding.ifc` (`VBB_FIXTURE1_IFC`), run by `verify_vissim.bat` | no |
| 41, 43, 45, 46 large IFC | large project IFC via `VBB_LARGE_IFC` | no |

Project IFC files are never committed. New tests go in `tests/` (pytest, synthetic IFC).

## Known baseline issue: Windows CP874

Confirmed on baseline `1cacbdb` during P0 (2026-11-13):
`tests/test_model_jobs.py::test_a_worker_that_dies_is_reported_in_plain_words`
reads its UTF-8 log with `Path.read_text()` without an encoding. With Windows
CP874 this raises `UnicodeDecodeError`; the same test passes with
`python -X utf8 -m pytest ...`. This is an existing test/environment issue,
not a P0 geometry regression. No application-wide encoding change was made.
