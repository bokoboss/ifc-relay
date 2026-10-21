# IFC Relay

**IFC → INPX Model Builder.** Review geometry, refine pedestrian areas, and build an INPX network for PTV Viswalk.

> IFC Relay (formerly *Viswalk BIM Builder*) is an independent tool. It is not made, endorsed or supported by PTV Group; PTV, Vissim and Viswalk are trademarks of their owner. It works with a licensed PTV Vissim/Viswalk 2025 or 2026 on the same computer.

**ภาษาไทย:** เครื่องมือช่วยเปลี่ยนแบบอาคาร/BIM ให้เป็นโมเดลเรขาคณิตสำหรับ PTV Viswalk ลดการขึ้นโมเดลซ้ำ โดยให้วิศวกรตรวจสอบและเลือกองค์ประกอบก่อนสร้างโมเดล ไม่ใช่ระบบแปลงไฟล์อัตโนมัติที่รับรองความถูกต้องโดยไม่ต้องตรวจ

> **Status:** v0.6.0 — supervised engineering pilot. Local-first, Windows-based Vissim/Viswalk integration. Not an official PTV product or a standalone production release.
>
> *Orchestrated by **KITTIPAT TANGITTINUNT**.*

## What are we building?

The goal is a **human-in-the-loop BIM-to-pedestrian-simulation model builder** for transportation and pedestrian engineers, BIM coordinators, and simulation modelers.

Preparing a pedestrian microsimulation model often requires manually redrawing floors, walls, columns, door openings, and vertical connections from architectural or structural drawings. BIM elements do not map one-to-one to walkable simulation geometry. This app aims to reduce that repetitive work while keeping assumptions, geometry, and exclusions reviewable.

Our intended workflow is:

```text
IFC / engineering drawings
        |
 Import + source audit
        |
 2D/3D inspection and object selection
        |
 Semantic geometry interpretation
        |
 Simplification + human review + validation
        |
 Deterministic geometry engine
        |
 Local PTV Vissim/Viswalk COM integration
        |
 .inpx + validation report + build log
```

**Design principle:** source data is not changed; user decisions remain separate; uncertain interpretation requires engineering review; downstream geometry creation is deterministic.

For product goals, scope, feature maturity and roadmap, see **[Product Vision & Scope](docs/PRODUCT_VISION.md)**.

## Capabilities and actual status

| Area | Current capability | Status |
| --- | --- | --- |
| IFC intake & audit | Read IFC metadata, units, storeys, categories and relationships | **Implemented; tested** |
| BIM explorer | 3D source inspection, storey/category filters, single-storey and whole-building views | **Implemented; tested** |
| Selection review | Auto / Include / Exclude / Review decisions per IFC GlobalId | **Implemented** |
| Revision carry-over | Re-apply review decisions to a new IFC revision by GlobalId; report dropped decisions and elements changed since the decision | **Implemented; synthetic-IFC tested** |
| Semantic model | Generate levels, floor areas, physical wall segments, column/obstacle representations | **Validated on small baseline** |
| Openings | Use door-filled openings to split walls; windows are not pedestrian passages | **Validated on small baseline** |
| Openings without doors | List unfilled wall openings, flag walkable-looking ones, open only those the engineer ticks | **Implemented; synthetic-IFC tested** |
| Non-straight walls | L/T/curved wall footprints exported as polygon obstacles with openings cut out | **Implemented; synthetic-IFC tested** |
| Large IFC workflow | Relevant-geometry filtering, per-storey loading, whole-building inspection | **Implemented; viewer tested on large IFC** |
| Walkable areas | Merge floor panels; track internal voids | **Implemented; unit tested; large-model QA pending** |
| Validation & export | Check geometry, download JSON, run local Vissim COM build and generate `.inpx` with reports | **Validated on small baseline** |
| Vertical circulation | Stair/ramp flights from mesh geometry, intermediate landing levels, level snapping, mezzanine levels ([details](docs/VERTICAL_CIRCULATION.md)) | **Implemented; stair direction checked in Vissim 2025 on the Revit sample; routing QA pending. Elevators planned** |
| Multi-storey walls/columns | Exported per storey, each cut by the openings at that storey's walking height | **Implemented; synthetic-IFC tested** |
| Off-level slabs | Slabs > 0.40 m from the storey floor wait for review (sunscreens, canopies); included ones become their own level | **Implemented; Revit-sample tested** |
| Connectivity diagnostic | Geometry-only check for walking zones nobody can reach and stairs that reach no floor | **Implemented; not routing verification** |
| Before build | Stops only on Geometry Engine errors; everything else is a Viswalk checklist (one confirmation, `_viswalk_checklist.md` + build manifest with hashes) | **Implemented ([policy](docs/ENGINEERING_GATE.md))** |
| 2D plan editor | Per-level plan: measure, add walkable floor / obstacle, open a passage through walls; rectangle or free polygon, vertex/edge snapping, Shift ortho lock, typed size, preview before save, undo/redo | **Implemented; browser E2E in CI** |
| Source vs pedestrian model | Click pedestrian-model objects, jump to their IFC source, overlay view | **Implemented** |
| Drawing inputs | Full DXF/PDF interpretation and editable 2D review in the app | **Planned; not supported by the current web workflow** |
| Pedestrian demand/results | Set origins/destinations, run simulation, summarize KPIs | **Longer-term extension; not implemented** |

**Validated baseline:** a small five-storey IFC was converted to semantic geometry, built as a Viswalk `.inpx` model via Vissim 2025 COM, reopened, and manually inspected. **This does not validate arbitrary IFC files.** The large structural-IFC workflow still needs full semantic/engineering QA before simulation use.

## Outputs

- Reviewed semantic/engine-facing geometry JSON.
- Locally generated Vissim/Viswalk `.inpx` (requires licensed Vissim 2025 or 2026 and a local `base_empty.inpx`).
- Validation results, model-building report, and build log.

## Architecture and boundaries

- **Source layer:** IFC first; drawing adapters are future work.
- **Interpretation layer:** IFC analysis, review selections, semantic geometry and simplification.
- **Validation/build layer:** deterministic engine and local Windows COM — no direct AI manipulation of `.inpx`.
- **The app is a model builder, not a replacement for the PTV simulation engine.** A file that opens successfully is not proof of correct pedestrian behavior, accessible circulation, or engineering fitness.

## Current repository limitations

The proven Geometry Engine v0.3 is bundled in `engine/` (private repository). The `base_empty.inpx` Vissim template is created with licensed Vissim and is **not** committed; place it in `local\` on each machine. Validation works without it; only the `.inpx` build needs it. The browser's Three.js libraries are downloaded by the installer rather than committed.

Structural IFC models may contain no doors or other information needed to establish pedestrian connections. Such gaps must be identified and reviewed, **not silently inferred as valid passages**. Multi-level stair/ramp/elevator extraction is not yet production-ready.

Large IFC: the 3D view loads at most 12,000 simulation-relevant meshes at once (storey by storey above that). Preparing the pedestrian model runs in a worker process with its own ceiling of 80,000 elements (`VBB_SEMANTIC_MAX_ELEMENTS`).

One copy of the app holds **one project for one engineer** (state in `runtime\`). Changes from several browser tabs are serialized and not lost, a long job never writes its result over a model that changed meanwhile, and only one Vissim build runs at a time; but tabs still share the same project. To work on two projects at once, use two copies of the app folder and start the second on another port (`scripts\start.ps1 -Port 8766`). The server listens on 127.0.0.1 only, answers only requests addressed to this computer and refuses changes sent from other web sites; it has no login, so it must not be exposed to a network.

## Quick start on Windows (no .exe)

Requires Windows 10/11, internet for the first install, and Python 3.10-3.13 (the installer can install Python 3.12 with `winget` if none is found). `Build Viswalk` additionally needs a licensed PTV Vissim 2025 or 2026.

1. Download the repository ZIP (or `git clone`) and extract it anywhere, e.g. `C:\Tools\viswalk-bim-builder`.
2. Copy `base_empty.inpx` (an empty network saved from the Vissim release you build with) into the `local\` folder (created by step 3), or pass it to the installer: `install.bat -BaseNetworkPath D:\proj\base_empty.inpx`. The Geometry Engine is bundled in `engine\`; `-EnginePath` copies an override into `local\`.
3. Double-click **`install.bat`**: creates `.venv` inside the app folder, installs packages, downloads the local Three.js runtime and checks Vissim COM.
4. Double-click **`start.bat`**: starts the app on `http://127.0.0.1:8765` and opens the browser. Close the window to stop it.
5. On the Vissim machine, double-click **`verify_vissim.bat`**: runs the automated tests (including engine-contract tests), Fixture #1 if `local\TallBuilding.ifc` exists, builds a synthetic verification model (straight stair, U-stair with landing, partial flight, L-wall, closed wall loop, door-less opening) through Vissim COM, and writes `output\verify_<time>\report.md` with a short manual checklist for Vissim. Use `verify_vissim.bat -SkipBuild` to skip the COM build.

**Check a real IFC without Vissim** (no `base_empty.inpx` needed):

```bat
verify_vissim.bat -Ifc "D:\Models\building.ifc" -SkipBuild
verify_vissim.bat -Ifc "D:\Models\building.ifc" -SkipBuild -Redact            &REM report safe to share
verify_vissim.bat -Ifc "D:\Models\building.ifc" -SkipBuild -StairsReviewOnly  &REM keep app default for stairs
```

Runs import (read-only, SHA-256 checked before/after) → IFC audit → geometry extraction → pedestrian-model conversion → Geometry Engine validation, and writes `output\ifc_check_<name>_<time>\report.md` and `report.json` with step timings, element counts, converted objects, skipped objects with reasons, all warnings and the engine result (PASS / WARN / FAIL). Passing this check is **not** a Viswalk check. `-Redact` removes the file name, paths and project/site/building/storey names from the report; unredacted intermediate files stay in `_private\`. Example: [`docs/examples/sample_ifc_check_report.md`](docs/examples/sample_ifc_check_report.md).

Lookup order (`project_paths.py`): engine `VBB_GEOMETRY_ENGINE` -> `local\` -> bundled `engine\` -> parent folder; base network and outputs `VBB_PROJECT_ROOT` -> `local\` -> parent folder. `local\` is git-ignored.

## Repository layout

```text
install.bat  start.bat  verify_vissim.bat   Windows entry points (no .exe)
app.py                      FastAPI server (uvicorn app:app)
ifc_service.py              IFC audit and storey/mesh listing
ifc_geometry_service.py     IFC geometry extraction
ifc_semantic_service.py     walkable areas, obstacles, openings, key ranges
ifc_vertical_service.py     stairs/ramps, landings, up-direction review
revision_service.py         carry review decisions across IFC revisions
vissim_build_service.py     validation and build orchestration
vissim_build_adapter.py     subprocess adapter around the Geometry Engine (COM)
state_store.py  project_paths.py  fixture_paths.py
static/                     browser UI (Three.js runtime downloaded to static/vendor/)
engine/                     bundled Geometry Engine v0.3
scripts/                    installer, launcher, verify and IFC dry-run scripts
tests/                      pytest suite on synthetic IFC (runs in CI)
checks/                     older numbered checks; 41/43/45/46 need a local IFC (VBB_LARGE_IFC)
examples/                   sample engine input
docs/                       design notes, product vision, history, sample report
legacy/                     DXF/PDF prototypes, superseded checks and launchers (reference only)
local/  output/             machine-specific files and results (git-ignored)
```

For development without the launchers: `pip install -r requirements.txt -r requirements-dev.txt`, then `python -m uvicorn app:app --host 127.0.0.1 --port 8765`. The browser needs the Three.js files in `static/vendor/` (`install.bat` downloads them).

## Engineering quality and roadmap

See [Product Vision & Scope](docs/PRODUCT_VISION.md) for acceptance criteria, risks and planned phases. Baseline regression scripts are included, but some tests require separately supplied IFC files and local Vissim.

Self-contained tests build synthetic IFC models in code and need no project files or Vissim:

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests
```

The same suite runs on every pull request via GitHub Actions. Large-IFC regression scripts (`checks/41`, `43`, `45`, `46`) read the fixture path from `VBB_LARGE_IFC`, so project file names never need to appear in the repository. Engine-contract tests run the bundled `engine/05_geometry_engine_v03.py` in validate-only mode (no Vissim, no base network) on every run, including CI; `VBB_GEOMETRY_ENGINE` can point to another copy.

Browser tests (Playwright + Chromium, `VBB_E2E=1`) cover the workflow and compare the main screens with reference images in `tests/e2e/visual/` (3D canvas hidden; compared over 4x4-pixel blocks so font rendering differences between Linux images do not count). The references are taken in CI by the **visual references** workflow (Actions tab, or a commit message containing `[visual-refs]`) and record their Chromium build; a run with another build skips the comparison. CI uploads the actual and diff images when a screen differs.

## Versions

| | |
| --- | --- |
| App | 0.6.0 (`version.py`) |
| Pedestrian-model (semantic) schema | 0.6.0 |
| Geometry Engine contract | v0.3 (`engine/05_geometry_engine_v03.py`) |
| Vissim | 2025 SP15 and 2026 tested (build, reopen in Viswalk, areas/stairs/walls checked). The build uses the newest installed release and falls back to the next one if it will not start; pick a release in the Engine menu or set `VBB_VISSIM_PROGID` |

The app reports these in *Engine ในเครื่อง* and writes them into every build manifest.

## Credits

Orchestrated by **KITTIPAT TANGITTINUNT** — product direction, engineering review and Vissim/Viswalk verification.

Interface type: IBM Plex Sans Thai and IBM Plex Mono (© IBM Corp., SIL Open Font License 1.1), bundled in `static/fonts/` so the app works offline.

## Data, trademark and licensing

- **Do not commit real client/project BIM data** (including IFC/DXF/PDF), proprietary Vissim models, credentials, cached geometry, logs or generated outputs.
- Use only synthetic or openly redistributable regression models whose provenance and licenses are confirmed.
- PTV Vissim and Viswalk are third-party products. This project is independent and not endorsed by PTV.
- **No software license has been selected yet.** A public GitHub repository alone does not grant reuse, redistribution or commercialization rights.
