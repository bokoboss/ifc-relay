# Viswalk BIM Builder

Local-first BIM-to-pedestrian-simulation model builder integrating IFC review, semantic geometry processing, and PTV Vissim/Viswalk COM automation.

> **Status:** Research prototype (POC). Requires a locally installed, appropriately licensed PTV Vissim/Viswalk with COM support. Not affiliated with or endorsed by PTV Group.

## Proven workflow

1. Import and audit IFC.
2. Review the source model in a 3D viewer, with storey and object filters.
3. Generate a semantic model (levels, walkable areas, physical walls, columns, openings, vertical connections).
4. Validate simulation geometry.
5. Build a local Vissim/Viswalk `.inpx` model through Windows COM.

The small IFC baseline has been built and manually validated in Vissim 2025. The large-model workflow adds storey-focused loading, geometry filtering, and walkable-area consolidation. It remains under evaluation.

## Architecture

```text
IFC / drawing sources
        |
  Audit + 3D Review
        |
  Reviewed Selection
        |
 Semantic Geometry
        |
 Validation + Simplification
        |
 Geometry Engine
        |
 Windows Vissim COM
        |
      .inpx
```

## Technical stack

Python, FastAPI, IfcOpenShell, Shapely, Three.js and PTV Vissim COM on Windows.

## Data and security

Do **not** commit private client or project IFC/DXF/PDF files, proprietary Vissim model files, credentials, build outputs, caches, or the Python virtual environment. Use shareable synthetic/open fixtures only and verify redistribution rights before adding assets.

## Source availability

Repository initialization is underway. Application code will be imported from the validated local v0.4.1a development package; this initial commit is documentation and repository safeguards only.

## License

No open-source license has yet been selected. Public visibility alone does not grant permission to reuse, redistribute, or commercialize the code.
