# Viswalk BIM Builder

**From BIM and engineering drawings to engineer-reviewed, simulation-ready pedestrian geometry.**

**ภาษาไทย:** เครื่องมือช่วยเปลี่ยนแบบอาคาร/BIM ให้เป็นโมเดลเรขาคณิตสำหรับ PTV Viswalk ลดการขึ้นโมเดลซ้ำ โดยให้วิศวกรตรวจสอบและเลือกองค์ประกอบก่อนสร้างโมเดล ไม่ใช่ระบบแปลงไฟล์อัตโนมัติที่รับรองความถูกต้องโดยไม่ต้องตรวจ

> **Status:** POC / active development — v0.4.1a source snapshot. Local-first, Windows-based Vissim/Viswalk integration. Not an official PTV product or a standalone production release.

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
| Vertical circulation | Stair/ramp flights from mesh geometry, intermediate landing levels, level snapping with explicit offsets ([details](docs/VERTICAL_CIRCULATION.md)) | **Implemented (v0.5 draft); synthetic-IFC tested; Vissim QA pending. Elevators planned** |
| Drawing inputs | Full DXF/PDF interpretation and editable 2D review in the app | **Planned; not supported by the current web workflow** |
| Pedestrian demand/results | Set origins/destinations, run simulation, summarize KPIs | **Longer-term extension; not implemented** |

**Validated baseline:** a small five-storey IFC was converted to semantic geometry, built as a Viswalk `.inpx` model via Vissim 2025 COM, reopened, and manually inspected. **This does not validate arbitrary IFC files.** The large structural-IFC workflow still needs full semantic/engineering QA before simulation use.

## Outputs

- Reviewed semantic/engine-facing geometry JSON.
- Locally generated Vissim/Viswalk `.inpx` (requires licensed Vissim 2025 and a local `base_empty.inpx`).
- Validation results, model-building report, and build log.

## Architecture and boundaries

- **Source layer:** IFC first; drawing adapters are future work.
- **Interpretation layer:** IFC analysis, review selections, semantic geometry and simplification.
- **Validation/build layer:** deterministic engine and local Windows COM — no direct AI manipulation of `.inpx`.
- **The app is a model builder, not a replacement for the PTV simulation engine.** A file that opens successfully is not proof of correct pedestrian behavior, accessible circulation, or engineering fitness.

## Current repository limitations

The proven Geometry Engine v0.3 is bundled in `engine/` (private repository). The `base_empty.inpx` Vissim template is created with licensed Vissim and is **not** committed; place it in `local\` on each machine. Validation works without it; only the `.inpx` build needs it. The browser's Three.js libraries are downloaded by the installer rather than committed.

Structural IFC models may contain no doors or other information needed to establish pedestrian connections. Such gaps must be identified and reviewed, **not silently inferred as valid passages**. Multi-level stair/ramp/elevator extraction is not yet production-ready.

## Quick start on Windows (no .exe)

Requires Windows 10/11, internet for the first install, and Python 3.10-3.13 (the installer can install Python 3.12 with `winget` if none is found). `Build Viswalk` additionally needs a licensed PTV Vissim 2025.

1. Download the repository ZIP (or `git clone`) and extract it anywhere, e.g. `C:\Tools\viswalk-bim-builder`.
2. Copy `base_empty.inpx` (an empty network saved from Vissim 2025) into the `local\` folder (created by step 3), or pass it to the installer: `install.bat -BaseNetworkPath D:\proj\base_empty.inpx`. The Geometry Engine is bundled in `engine\`; `-EnginePath` copies an override into `local\`.
3. Double-click **`install.bat`**: creates `.venv` inside the app folder, installs packages, downloads the local Three.js runtime and checks Vissim COM.
4. Double-click **`start.bat`**: starts the app on `http://127.0.0.1:8765` and opens the browser. Close the window to stop it.
5. On the Vissim machine, double-click **`verify_vissim.bat`**: runs the automated tests (including engine-contract tests), Fixture #1 if `local\TallBuilding.ifc` exists, builds a synthetic verification model (straight stair, U-stair with landing, partial flight, L-wall, closed wall loop, door-less opening) through Vissim COM, and writes `output\verify_<time>\report.md` with a short manual checklist for Vissim. Use `verify_vissim.bat -SkipBuild` to skip the COM build.

Lookup order (`project_paths.py`): engine `VBB_GEOMETRY_ENGINE` -> `local\` -> bundled `engine\` -> parent folder; base network and outputs `VBB_PROJECT_ROOT` -> `local\` -> parent folder. `local\` is git-ignored.

## Local development (Windows)

1. Clone the repository to the intended local project folder.
2. Prepare a Python environment and install packages from `requirements.txt`.
3. Run `setup_app.ps1` to install Python dependencies and locally hosted Three.js modules (initial setup requires internet).
4. Run `run_app.ps1` and open `http://127.0.0.1:8765`.
5. For `.inpx` export, configure licensed PTV Vissim 2025 COM and place `base_empty.inpx` in `local\` (or the parent folder, original layout). The engine is bundled in `engine/`.

The present scripts assume a local project layout and are not yet packaged as a one-click installer.

## Engineering quality and roadmap

See [Product Vision & Scope](docs/PRODUCT_VISION.md) for acceptance criteria, risks and planned phases. Baseline regression scripts are included, but some tests require separately supplied IFC files and local Vissim.

Self-contained tests build synthetic IFC models in code and need no project files or Vissim:

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests
```

The same suite runs on every pull request via GitHub Actions. Large-IFC regression scripts (41/43/45/46) read the fixture path from `VBB_LARGE_IFC`, so project file names never need to appear in the repository. Engine-contract tests run the bundled `engine/05_geometry_engine_v03.py` in validate-only mode (no Vissim, no base network) on every run, including CI; `VBB_GEOMETRY_ENGINE` can point to another copy.

## Data, trademark and licensing

- **Do not commit real client/project BIM data** (including IFC/DXF/PDF), proprietary Vissim models, credentials, cached geometry, logs or generated outputs.
- Use only synthetic or openly redistributable regression models whose provenance and licenses are confirmed.
- PTV Vissim and Viswalk are third-party products. This project is independent and not endorsed by PTV.
- **No software license has been selected yet.** A public GitHub repository alone does not grant reuse, redistribution or commercialization rights.
