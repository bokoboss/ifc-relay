# Public IFC models for testing

IFC files are never committed to this repository (see `.gitignore`). Download them locally and run:

```bat
.\verify_vissim.bat -Ifc "C:\path\model.ifc" -SkipBuild
```

| Model | What it contains | Source | Licence |
| --- | --- | --- | --- |
| Revit "Advanced Sample Project" (`BuildingBIMModel.ifc`, IFC4, 26 MB) | Architectural: 5 storeys, 146 walls, 100 doors, 10 stairs / 20 flights with landings, 30 railings, 116 spaces | [viktor-platform/ifc-sample-models](https://github.com/viktor-platform/ifc-sample-models/tree/main/sample-models) | No licence file in that repository; the model is Autodesk's Revit sample. Use for internal testing only, do not redistribute. |
| buildingSMART Simple-Scene `Building-Architecture.ifc` (IFC2x3 / IFC4 / IFC4.3) | Single storey, 4 walls, 3 slabs, 2 spaces; no doors or stairs | [buildingSMART/Sample-Test-Files](https://github.com/buildingSMART/Sample-Test-Files) | CC BY 4.0 (buildingSMART International) |
| viktor `SampleBuilding.ifc` (IFC4, 6.7 MB) | 12 storeys, 108 slabs, 58 walls; structural, no doors or stairs | [viktor-platform/ifc-sample-models](https://github.com/viktor-platform/ifc-sample-models/tree/main/sample-models) | No licence file; internal testing only |

## Results on the Revit advanced sample (dry run, 2026-10-20)

- 742 of 742 elements meshed, engine errors 0, source unchanged.
- All 20 stair flights connect storey -> generated landing -> storey with zero offsets (after the area-weighted storey datum fix).
- 83 doors applied to wall openings; 17 doors have no `IfcRelFillsElement` link and are not converted.
- FLOOR-typed "Metal Sunscreen" panels are imported as walkable floor by default and should be excluded in review.
- Engine warnings: 146 wall + wall overlaps (joined Revit walls), 12 columns and 4 railings with no floor under them.
