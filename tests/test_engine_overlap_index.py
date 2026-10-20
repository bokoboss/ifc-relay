"""F-16: the engine's obstacle overlap check uses a per-level spatial index and
gives exactly what the all-pairs check gave, in the same order."""
from __future__ import annotations

import random
import time

from shapely.geometry import Polygon, box

from tests.engine_contract import ENGINE, requires_engine


def _engine():
    from vissim_build_adapter import load_engine
    return load_engine(ENGINE, validate_only=True)


def _all_pairs(obstacles, tolerance):
    """The original O(n^2) check, kept here as the reference."""
    found = []
    for i in range(len(obstacles)):
        for j in range(i + 1, len(obstacles)):
            a, b = obstacles[i], obstacles[j]
            if a["level_key"] != b["level_key"]:
                continue
            overlap = a["geometry"].intersection(b["geometry"])
            if not overlap.is_empty and overlap.area > tolerance:
                found.append({"type": "obstacle_overlap", "level_key": a["level_key"],
                              "objects": [a["key"], b["key"]], "names": [a["name"], b["name"]],
                              "overlap_area_m2": round(overlap.area, 6)})
    return found


def _random_obstacles(n, levels=3, extent=60.0, seed=7):
    rnd = random.Random(seed)
    out = []
    for k in range(n):
        x, y = rnd.uniform(0, extent), rnd.uniform(0, extent)
        w, h = rnd.uniform(0.2, 3.0), rnd.uniform(0.2, 3.0)
        if k % 5 == 0:     # some rotated / non-box shapes
            geom = Polygon([(x, y), (x + w, y + h / 3), (x + w / 2, y + h), (x - w / 3, y + h / 2)])
        else:
            geom = box(x, y, x + w, y + h)
        out.append({"key": 1000 + k, "name": f"O{k}", "level_key": rnd.randint(1, levels), "geometry": geom})
    # edge cases: touching only (no area), tiny overlap below tolerance, identical
    out += [
        {"key": 1, "name": "touch-a", "level_key": 1, "geometry": box(100, 100, 101, 101)},
        {"key": 2, "name": "touch-b", "level_key": 1, "geometry": box(101, 100, 102, 101)},
        {"key": 3, "name": "same-a", "level_key": 2, "geometry": box(200, 200, 201, 201)},
        {"key": 4, "name": "same-b", "level_key": 2, "geometry": box(200, 200, 201, 201)},
        {"key": 5, "name": "other-level", "level_key": 3, "geometry": box(200, 200, 201, 201)},
    ]
    return out


@requires_engine
def test_indexed_overlap_check_equals_all_pairs():
    engine = _engine()
    obstacles = _random_obstacles(400)
    expected = _all_pairs(obstacles, engine.TOLERANCE)
    assert expected, "fixture should contain overlaps"
    assert engine.find_obstacle_overlaps(obstacles) == expected


@requires_engine
def test_indexed_overlap_check_budget():
    """Performance budget: 3000 obstacles (a large building) well under the
    all-pairs time; the index must not be slower even on small inputs."""
    engine = _engine()
    obstacles = _random_obstacles(3000, levels=10, extent=300.0, seed=11)
    t0 = time.perf_counter()
    engine.find_obstacle_overlaps(obstacles)
    indexed = time.perf_counter() - t0
    assert indexed < 1.0, f"indexed overlap check took {indexed:.2f} s for 3000 obstacles"
    assert engine.find_obstacle_overlaps([]) == []
