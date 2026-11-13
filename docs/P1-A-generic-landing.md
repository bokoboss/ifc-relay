# P1-A: minimal generic landing evidence and regression boundary

Date: 2026-11-13. Baseline: `eb913ab078dbb3727c16119a5644574b372c5c2a`.
Branch: `codex/p1-a-minimal-generic-landing`.
Status: **Scope Verified / Regression Coverage Added**.
Local commit approved; this is not Generic Landing Implemented.

## Decision

No production detection rule added. The inspected local models provide no
undefined slab or proxy/part/plate landing examples under an IfcStair relationship.
Per the approved no-example fallback, this change adds synthetic regression
coverage only. It does **not** claim new generic landing conversion support.

## IFC evidence

Read-only STEP relationship inventory of the nine `.ifc` files in `IFC Model/`.
Followed IfcRelAggregates and IfcRelNests from IfcStair, including descendants;
checked slab classification and proxy/part/plate membership. This is a textual
inventory of these exports, not a general STEP parser or geometric certification.

| Model | IfcStair | Slabs under stairs (all LANDING) | Flights under stairs | Members under stairs |
| --- | ---: | ---: | ---: | ---: |
| 1ST_ONLY_Bangsue Grand Station_detached.ifc | 97 | 176 | 289 | 0 |
| 2019_01_09_Bangsue Grand Station (1).ifc | 101 | 190 | 307 | 0 |
| BuildingBIMModel.ifc | 10 | 10 | 20 | 72 |
| PK_10.ifc | 9 | 44 | 46 | 208 |
| SampleBuilding.ifc | 0 | 0 | 0 | 0 |
| TallBuilding.ifc | 0 | 0 | 0 | 0 |
| TYPE4_PK16.ifc | 13 | 33 | 49 | 185 |
| YL_18_20181226.ifc | 13 | 46 | 57 | 244 |
| สตง 30 ชั้น.ifc | 3 | 1 | 4 | 0 |

Concrete examples:

- BuildingBIMModel: relationship `#282353`, parent stair `#264328`, slab
  `#264873`, GlobalId `2GoXeF051238RZ7lkh7zBj`, explicitly `.LANDING.`.
  The same relationship includes member `#264887`, GlobalId
  `2GoXeF051238RZ7lkh7z8z`, explicitly `.STRINGER.`. Parent stair alone is
  insufficient evidence that every child is a landing.
- PK_10: relationship `#3389097`, parent `#1794096`, slab `#1794514`,
  GlobalId `3ax6UzR9zAwOd4n1DWzqu9`, explicitly `.LANDING.`; member
  `#1808771` is described as Stringer 1.
- สตง 30 ชั้น: relationship `#825961`, parent `#145302`, slab `#145832`,
  GlobalId `3uwHzQebvFGRuHhS2jfJdo`, explicitly `.LANDING.`.

Detailed local inventory is in ignored `runtime/p1a_inventory_verified.json`.
IFC files were read only. Archived RAR models and all other machine locations
were not exhaustively inspected; the table defines the verified scope.

## Regression coverage and validation

`tests/test_generic_landing_scope.py`: six cases combining undefined slab,
generic proxy, and stringer with aggregate and nest relationships. The added
objects overlap an existing floor or an explicit intermediate landing. All stay
in review by default; Areas, Levels, vertical connections and Obstacles exactly
match the model before the ambiguous child was added. Aggregate undefined slab
also retains its unresolved landing ledger entry with `selection_review`.

Focused command (isolated synthetic fixtures):

```powershell
.venv/Scripts/python -m pytest tests/test_generic_landing_scope.py tests/test_landing_ledger.py tests/test_landing_preservation.py -q -p no:cacheprovider --basetemp runtime/p1a-test-final
```

Result: **17 passed**, 20.83 seconds. Existing coverage includes IFC2X3/IFC4
landing ledger outcomes, floor contribution, shaft voids, connectivity of a small
landing, rotated components and terminal landing level routing. Initial sandbox
temp permission errors were resolved by running with approved filesystem access;
the initial nest fixture argument was corrected before the passing run.

## Limits

Undefined/generic landing auto-conversion remains unproved and unchanged.
Generic proxies retain ordinary classification review; nested undefined slabs
are not added to the existing aggregate-only landing ledger. No reconstruction,
new mesh processing or decomposition was introduced. Explicit landing conversion
continues through the existing pipeline.

No COM, P0/P2 smoke rerun, full suite, CI, live project mutation, push, merge,
deployment was performed. Local commit was subsequently approved for the two
P1-A test and documentation files only.
