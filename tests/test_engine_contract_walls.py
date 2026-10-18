from __future__ import annotations

from tests.engine_contract import engine_validate, issue_types, requires_engine
from tests.ifc_factory import Building, add_opening, add_wall, semantic_for
from tests.test_openings_and_wall_shapes import _ring_wall


@requires_engine
def test_engine_accepts_polygon_walls_and_opened_door_less_opening(tmp_path):
    b = Building([0.0])
    b.slab([(0, 0), (12, 0), (12, 8), (0, 8)], 0.0, b.storeys[0])
    wall = add_wall(b, 0.5, 6.0, 10.0, b.storeys[0])
    opening = add_opening(b, wall, 4.0, 5.0, 6.0, 0.0, 2.1)
    pts = [(8, 1), (11, 1), (11, 1.2), (8.2, 1.2), (8.2, 4), (8, 4)]
    n = len(pts)
    b.mesh_element("IfcWall", [(x, y, 0) for x, y in pts] + [(x, y, 3) for x, y in pts],
                   [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
                   + [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)], storey=b.storeys[0])
    _ring_wall(b, b.storeys[0])
    sem = semantic_for(b.write(tmp_path / "walls.ifc"), {opening.GlobalId: "include"})
    v = engine_validate(sem, tmp_path)
    assert v["build_allowed"]
    # every engine obstacle is a single hole-free polygon (no extra Vissim parts)
    assert v["summary"]["vissim_obstacles"] == v["summary"]["semantic_obstacles"]
    assert "obstacle_overlap" not in issue_types(v)
