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
| Semantic model | Generate levels, floor areas, physical wall segments, column/obstacle representations | **Validated on small baseline** |
| Openings | Use door-filled openings to split walls; windows are not pedestrian passages | **Validated on small baseline** |
| Large IFC workflow | Relevant-geometry filtering, per-storey loading, whole-building inspection | **Implemented; viewer tested on large IFC** |
| Walkable areas | Merge floor panels; track internal voids | **Implemented; unit tested; large-model QA pending** |
| Validation & export | Check geometry, download JSON, run local Vissim COM build and generate `.inpx` with reports | **Validated on small baseline** |
| Vertical circulation | Resolve true stair/ramp/elevator geometry and floor-to-floor links | **Planned / under development** |
| Drawing inputs | Full DXF/PDF interpretation and editable 2D review in the app | **Planned; not supported by the current web workflow** |
| Pedestrian demand/results | Set origins/destinations, run simulation, summarize KPIs | **Longer-term extension; not implemented** |

**Validated baseline:** a small five-storey IFC was converted to semantic geometry, built as a Viswalk `.inpx` model via Vissim 2025 COM, reopened, and manually inspected. **This does not validate arbitrary IFC files.** The large structural-IFC workflow still needs full semantic/engineering QA before simulation use.

## Outputs

- Reviewed semantic/engine-facing geometry JSON.
- Locally generated Vissim/Viswalk `.inpx` (requires the installed licensed software and supporting engine files).
- Validation results, model-building report, and build log.

## Architecture and boundaries

- **Source layer:** IFC first; drawing adapters are future work.
- **Interpretation layer:** IFC analysis, review selections, semantic geometry and simplification.
- **Validation/build layer:** deterministic engine and local Windows COM — no direct AI manipulation of `.inpx`.
- **The app is a model builder, not a replacement for the PTV simulation engine.** A file that opens successfully is not proof of correct pedestrian behavior, accessible circulation, or engineering fitness.

## Current repository limitations

This public source snapshot does **not** include the proven standalone `05_geometry_engine_v03.py` or the local `base_empty.inpx` Vissim template. Both are external development dependencies requiring appropriate rights. Without them, the public clone cannot complete the `.inpx` build flow. The browser's Three.js libraries are downloaded by `setup_app.ps1` rather than committed.

Structural IFC models may contain no doors or other information needed to establish pedestrian connections. Such gaps must be identified and reviewed, **not silently inferred as valid passages**. Multi-level stair/ramp/elevator extraction is not yet production-ready.

## Local development (Windows)

1. Clone the repository to the intended local project folder.
2. Prepare a Python environment and install packages from `requirements.txt`.
3. Run `setup_app.ps1` to install Python dependencies and locally hosted Three.js modules (initial setup requires internet).
4. Run `run_app.ps1` and open `http://127.0.0.1:8765`.
5. For `.inpx` export, configure licensed PTV Vissim 2025 COM and place the separately supplied geometry engine and Vissim base model at the expected parent-folder paths.

The present scripts assume a local project layout and are not yet packaged as a one-click installer.

## Engineering quality and roadmap

See [Product Vision & Scope](docs/PRODUCT_VISION.md) for acceptance criteria, risks and planned phases. Baseline regression scripts are included, but some tests require separately supplied IFC files and local Vissim.

## Data, trademark and licensing

- **Do not commit real client/project BIM data** (including IFC/DXF/PDF), proprietary Vissim models, credentials, cached geometry, logs or generated outputs.
- Use only synthetic or openly redistributable regression models whose provenance and licenses are confirmed.
- PTV Vissim and Viswalk are third-party products. This project is independent and not endorsed by PTV.
- **No software license has been selected yet.** A public GitHub repository alone does not grant reuse, redistribution or commercialization rights.
