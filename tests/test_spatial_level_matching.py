from __future__ import annotations

import pytest

from ifc_vertical_service import assign_landing_levels, cluster_landing_levels
from tests.ifc_factory import Building, semantic_for


def test_physical_planes_do_not_chain_or_average_distinct_heights():
    heights = [1.0, 1.2, 1.4, 1.6, 1.62]
    levels = cluster_landing_levels(heights, [])
    assert [lv["z"] for lv in levels] == heights


def test_assignment_is_complete_unique_and_bounded_even_with_explicit_tolerance():
    levels, assigned = assign_landing_levels([1, 1.2, 1.4, 1.6, 4], [{"key": 2, "z": 4}], tolerance=.25)
    assert len(assigned) == 5 and assigned[-1] == 2
    by_key = {lv["key"]: lv["z"] for lv in levels}
    assert [lv["z"] for lv in levels] == [1, 1.4]
    assert all(abs(z - by_key[k]) <= .25 for z, k in zip([1, 1.2, 1.4, 1.6], assigned))


def test_a_different_stair_parent_cannot_supply_the_endpoint(tmp_path):
    b = Building([0, 4])
    stair, other = b.stair(b.storeys[0]), b.stair(b.storeys[0])
    b.flight(2, 6, 1, 2, 0, 2, parent=stair)
    b.slab([(6, 1), (8, 1), (8, 2), (6, 2)], 2, None, predefined="LANDING", parent=other)
    sem = semantic_for(b.write(tmp_path / "unrelated.ifc"), {stair.GlobalId: "include"})
    assert sem["vertical_connections"][0]["endpoint_support"]["end"]["status"] == "unresolved"


def test_close_landing_planes_both_survive_with_one_assignment(tmp_path):
    b = Building([0, 4])
    stair = b.stair(b.storeys[0])
    slabs = [b.slab([(x, 0), (x + 2, 0), (x + 2, 2), (x, 2)], z, None,
                    predefined="LANDING", parent=stair) for x, z in [(0, 1.7), (5, 1.72)]]
    sem = semantic_for(b.write(tmp_path / "planes.ifc"))
    level_z = {lv["key"]: lv["z"] for lv in sem["levels"]}
    for slab, z in zip(slabs, [1.7, 1.72]):
        areas = [a for a in sem["areas"] if slab.GlobalId in a.get("ifc_source_global_ids", [])]
        assert len(areas) == 1 and level_z[areas[0]["level_key"]] == pytest.approx(z)


def test_height_only_far_landing_is_not_an_exact_endpoint_match(tmp_path):
    b = Building([0, 4])
    b.slab([(0, 0), (10, 0), (10, 6), (0, 6)], 0, b.storeys[0])
    stair = b.stair(b.storeys[0])
    b.flight(2, 6, 1, 2, 0, 1.7, parent=stair)
    b.slab([(100, 1), (102, 1), (102, 3), (100, 3)], 1.7, None,
           predefined="LANDING", parent=stair)
    sem = semantic_for(b.write(tmp_path / "far.ifc"), {stair.GlobalId: "include"})
    [vc] = sem["vertical_connections"]
    assert vc["level_match"]["end"] != "exact"
    assert vc["endpoint_support"]["end"]["status"] == "unresolved"
    assert any(d["code"] == "stair_endpoint_unresolved" for d in sem["ifc_semantic"]["diagnostics"])


@pytest.mark.parametrize("has_riser", [True, False])
def test_one_riser_requires_attribute_and_local_support(tmp_path, has_riser):
    b = Building([0, 4])
    b.slab([(0, 0), (6, 0), (6, 4), (0, 4)], 0, b.storeys[0])
    stair = b.stair(b.storeys[0])
    attrs = {"RiserHeight": .17 / b.scale} if has_riser else {}
    b.flight(2, 6, 1, 2, 0, 1.53, parent=stair, **attrs)
    b.slab([(6, 1), (8, 1), (8, 2), (6, 2)], 1.7, None,
           predefined="LANDING", parent=stair)
    sem = semantic_for(b.write(tmp_path / "riser.ifc"), {stair.GlobalId: "include"})
    [vc] = sem["vertical_connections"]
    if has_riser:
        assert vc["level_match"]["end"] == "riser_adjusted"
        assert vc["end_z_offset"] == 0
        assert vc["endpoint_support"]["end"]["reason"] == "ifc_riser_height"
    else:
        assert vc["level_match"]["end"] == "offset"
        assert vc["endpoint_support"]["end"]["status"] == "unresolved"
