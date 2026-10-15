from __future__ import annotations

from shapely.geometry import Polygon

from ifc_semantic_service import hole_polygons, merge_walkable_components


def rect(x1, y1, x2, y2):
    return Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])


def check(name, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {name}")
    if not condition:
        raise AssertionError(name)


def main() -> int:
    print("Walkable Surface Consolidation v0.4.1")
    print("=" * 68)

    adjacent = [rect(0, 0, 5, 5), rect(5, 0, 10, 5)]
    merged = merge_walkable_components(adjacent)
    check("two adjacent slab panels merge to one walkable region", len(merged) == 1)
    check("merged area preserved", abs(merged[0].area - 50.0) < 1e-6)

    ring = [
        rect(0, 0, 10, 2),
        rect(0, 8, 10, 10),
        rect(0, 2, 2, 8),
        rect(8, 2, 10, 8),
    ]
    ring_merged = merge_walkable_components(ring)
    check("ring panels consolidate to one exterior region", len(ring_merged) == 1)
    holes = hole_polygons(ring_merged[0])
    check("central floor void is preserved", len(holes) == 1)
    check("central void area preserved", abs(holes[0].area - 36.0) < 1e-6)

    separated = [rect(0, 0, 2, 2), rect(5, 0, 7, 2)]
    separated_merged = merge_walkable_components(separated)
    check("disconnected floor regions stay separate", len(separated_merged) == 2)

    print("=" * 68)
    print("WALKABLE MERGE CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
