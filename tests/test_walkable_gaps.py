"""Viswalk connects walkable elements only where they touch or overlap: no gaps."""
from __future__ import annotations

from shapely.geometry import Polygon
from shapely.ops import unary_union

from ifc_semantic_service import merge_walkable_components
from tests.engine_contract import engine_validate, issue_types, requires_engine
from tests.ifc_factory import Building, semantic_for


def test_slab_joint_gap_is_closed_but_real_gap_is_kept():
    stats: dict[str, int] = {}
    joined = merge_walkable_components([Polygon([(0, 0), (5, 0), (5, 5), (0, 5)]),
                                        Polygon([(5.01, 0), (10, 0), (10, 5), (5.01, 5)])], stats=stats)
    assert len(joined) == 1 and stats == {"gaps_closed": 1}
    assert abs(joined[0].area - 50.0) < 0.06                     # outer edges unchanged
    apart = merge_walkable_components([Polygon([(0, 0), (5, 0), (5, 5), (0, 5)]),
                                       Polygon([(5.2, 0), (10, 0), (10, 5), (5.2, 5)])])
    assert len(apart) == 2


def test_building_with_slab_joints_has_one_continuous_floor(tmp_path):
    b = Building([0.0, 3.4])
    l1, _ = b.storeys
    for x0 in (0.0, 6.01, 12.02):                                  # 10 mm joints
        b.slab([(x0, 0), (x0 + 6, 0), (x0 + 6, 8), (x0, 8)], 0.0, l1)
    sem = semantic_for(b.write(tmp_path / "joints.ifc"))
    assert len([a for a in sem["areas"] if a["level_key"] == 1]) == 1
    assert any("closed 2 gap(s)" in w for w in sem["ifc_semantic"]["warnings"])
    assert not sem["ifc_semantic"]["connectivity"]["isolated_zones"]


@requires_engine
def test_overlapping_manual_floor_is_accepted_by_the_engine(tmp_path):
    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model

    b = Building([0.0, 3.4])
    b.slab([(0, 0), (10, 0), (10, 8), (0, 8)], 0.0, b.storeys[0])
    path = b.write(tmp_path / "overlap.ifc")
    edit = {"id": "E1", "kind": "walkable", "level_key": 1, "polygon": [[9, 2], [14, 2], [14, 6], [9, 6]]}
    sem = build_semantic_model(path, extract_ifc_geometry(path), {}, [edit])
    level = [Polygon(a["polygon"]) for a in sem["areas"] if a["level_key"] == 1]
    assert len(level) == 2 and level[0].intersection(level[1]).area > 0.5   # overlap, not a seam
    assert unary_union(level).geom_type == "Polygon"
    validation = engine_validate(sem, tmp_path)
    assert validation["build_allowed"] and "area_overlap" not in issue_types(validation)
