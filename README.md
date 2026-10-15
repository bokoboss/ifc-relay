# Viswalk BIM Builder

Local-first experimental BIM-to-pedestrian-simulation model builder for PTV Vissim/Viswalk.

> **Status:** POC / active development. Not an official PTV product. Requires licensed local PTV Vissim/Viswalk with COM on Windows.

## Features

- IFC auditing and building-storey/category inspection
- 3D IFC preview, single-storey and whole-building modes
- Selection/review model for simulation-relevant objects
- IFC to semantic pedestrian geometry: Levels, Areas, Walls, Doors, Columns
- Walkable floor-panel consolidation and large-IFC preflight
- Geometry validation and Windows COM `.inpx` builder

## Architecture

```
IFC -> audit -> 3D review -> semantic model -> validate -> geometry engine -> Vissim COM -> .inpx
```

## Status and limitations

- The TallBuilding IFC baseline completed import, geometry generation and manual Vissim inspection.
- Large structural IFCs need further validation of floor areas, openings and vertical movement.
- Structural BIM without doors cannot automatically provide valid pedestrian openings.
- Stair, ramp, elevator semantics are still under development.
- The proven standalone `05_geometry_engine_v03.py` and `base_empty.inpx` are external local development dependencies **not included in this initial public source snapshot**. Building `.inpx` from this snapshot requires supplying these separately with appropriate rights. This is not a standalone release.
- The JavaScript 3D viewer dependencies are downloaded by `setup_app.ps1` and are not committed.

## Local setup (Windows)

1. Create a Python virtual environment in the parent project folder.
2. Install `requirements.txt`.
3. Run `setup_app.ps1` to install runtime browser libraries (requires internet connectivity).
4. Run `run_app.ps1` and open the displayed local URL.
5. For COM export, install and configure Vissim 2025, and provide the external Geometry Engine and Vissim base model files in the parent folder.

## Tests

See `41_check_large_ifc_fixture_v041.py`, `42_check_walkable_merge_v041.py`, `43_check_large_ifc_preflight_v041.py`, and `46_check_storey_autoselect_v041a.py`. Certain integration tests require locally provided IFC fixtures and Vissim.

## Data policy

Do not commit client or project BIM assets, proprietary model files, raw datasets, passwords, `.env`, generated geometry, logs, caches, or installed binaries. Only use redistributable fixtures with documented provenance.

## License

No open-source license has been selected yet. Public repository visibility does not confer reuse rights.
