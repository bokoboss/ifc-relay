# P1-A — Generic Landing Scope and Regression Coverage

**Status:** Scope Verified / Regression Coverage Added. Automatic generic-landing reconstruction was not implemented.

## Decision

No production detection heuristic was added. The reviewed IFC models did not contain sufficiently evidenced, unclassified landing examples that would justify a new conversion rule. Ambiguous stair members remain subject to Engineering Review.

## Source evidence (aggregate only)

A read-only review covered **nine locally available IFC models** and examined IfcRelAggregates and IfcRelNests relationships, slab classifications, and selected stair members.

Across the inspected models, **500 slabs identified under stairs were explicitly classified as LANDING**. No unambiguous undefined slab, proxy, part, or plate landing was established within the reviewed sample. The inspection was a relationship/classification inventory, not a geometric certification or comprehensive survey of all locally held archives.

Individual model filenames, project names, source IFC identifiers, relationship/entity numbers, local paths, and per-model inventory counts are deliberately excluded from this public document. The original project inventory is not included in the repository.

## Regression boundary

tests/test_generic_landing_scope.py adds six synthetic cases covering:
- Undefined slab, generic proxy, and stringer member types.
- Aggregate and nest relationships with a stair.
- Ambiguous child objects overlapping an existing floor or an explicit intermediate landing.

Each ambiguous child remains in Review by default. It does not introduce duplicate Walkable Areas, Levels, Flights, or Obstacles. The aggregate undefined-slab case retains an unresolved landing ledger entry indicating selection review.

The focused local suite covering this test and the existing landing ledger/preservation regressions passed **17 tests**. The clean integration suite subsequently passed **85 focused tests**. This note does not claim a new COM run, a full-building pedestrian simulation, or generic-landing conversion support.

## Limits and follow-up

The inspection covers only the nine models actually reviewed, not every local file or archive. Generic landing auto-conversion remains unimplemented until a genuine source case can be inspected and an evidence-based rule justified. Do not reconstruct floor geometry from gaps or infer connections from level proximity alone.

All real source identifiers and source files must stay outside public Git history and pull requests.
