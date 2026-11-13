from __future__ import annotations

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from gate_service import evaluate_gate
from tests.ifc_factory import Building, semantic_for


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4"])
def test_landing_ledger_outcomes_and_per_component_mapping(tmp_path, schema):
    b = Building([0, 4], schema=schema)
    stair = b.stair(b.storeys[0])
    b.slab([(0, 0), (4, 0), (4, 4), (0, 4)], 4, b.storeys[1])
    terminal = b.slab([(4, 0), (5, 0), (5, .7), (4, .7)], 4, None,
                      predefined="LANDING", parent=stair)
    middle = b.slab([(6, 0), (8, 0), (8, 2), (6, 2)], 2, None,
                    predefined="LANDING", parent=stair)
    excluded = b.slab([(10, 0), (12, 0), (12, 2), (10, 2)], 2, None,
                      predefined="LANDING", parent=stair)
    missing = b._run("root.create_entity", ifc_class="IfcSlab", predefined_type="LANDING")
    b._run("aggregate.assign_object", relating_object=stair, products=[missing])
    sem = semantic_for(b.write(tmp_path / "ledger.ifc"), {excluded.GlobalId: "exclude"})
    info = sem["ifc_semantic"]
    ledger = {row["source_global_id"]: row for row in info["landing_ledger"]}
    assert len(ledger) == 4
    assert ledger[terminal.GlobalId]["outcome"] == "contributed_to_existing_area"
    assert ledger[middle.GlobalId]["outcome"] == "represented"
    assert ledger[excluded.GlobalId]["outcome"] == "excluded"
    assert ledger[missing.GlobalId]["outcome"] == "unresolved"
    for guid in (terminal.GlobalId, middle.GlobalId):
        row = ledger[guid]
        assert row["output_area_keys"] and row["components"]
        assert all(c["covered"] and c["coverage_ratio"] > .999 for c in row["components"])
    summary = info["summary"]
    assert summary["source_landings"] == 4
    assert summary["landings_represented"] == 2
    assert summary["landings_review"] == 1
    assert summary["landings_excluded"] == 1
    assert summary["landings_omitted"] == 1
    gate = evaluate_gate(sem, {"build_allowed": True, "issues": [], "severity_counts": {}})
    assert gate["passed"] and "landing_review" in gate["to_check"]
    assert gate["verification"]["viswalk_verified"] is False


def test_landing_shaft_hole_remains_a_void(tmp_path):
    b = Building([0, 4])
    stair = b.stair(b.storeys[0])
    for p in [box(0, 0, 4, 1), box(0, 3, 4, 4), box(0, 1, 1, 3), box(3, 1, 4, 3)]:
        b.slab(list(p.exterior.coords)[:-1], 2, None, predefined="LANDING", parent=stair)
    sem = semantic_for(b.write(tmp_path / "shaft.ifc"))
    level = next(lv["key"] for lv in sem["levels"] if lv.get("generated"))
    floor = unary_union([Polygon(a["polygon"]) for a in sem["areas"] if a["level_key"] == level])
    masks = unary_union([Polygon(o["polygon"]) for o in sem["obstacles"]
                         if o.get("type") == "walkable_void_mask" and o["level_key"] == level])
    assert floor.difference(masks).intersection(box(1.01, 1.01, 2.99, 2.99)).area == 0
    assert len(sem["ifc_semantic"]["landing_ledger"]) == 4


def test_small_evidenced_landing_is_kept_in_connectivity(tmp_path):
    b = Building([0, 4])
    b.slab([(0, 0), (2, 0), (2, 3), (0, 3)], 0, b.storeys[0])
    stair = b.stair(b.storeys[0])
    b.flight(1, 4, 1, 1.7, 0, 2, parent=stair)
    b.slab([(4, 1), (5, 1), (5, 1.7), (4, 1.7)], 2, None,
           predefined="LANDING", parent=stair)
    sem = semantic_for(b.write(tmp_path / "small.ifc"), {stair.GlobalId: "include"})
    con = sem["ifc_semantic"]["connectivity"]
    assert con["zones"] == 2 and con["stairs_linked"] == 1
    assert not con["stairs_not_linked"]


def test_existing_floor_joint_hole_policy_survives_an_unrelated_landing(tmp_path):
    from tests.test_hardening import _ring_with_hole
    b = Building([0])
    _ring_with_hole(b, b.storeys[0], 5, 5, 5.1, 5.1)
    stair = b.stair(b.storeys[0])
    b.slab([(12, 0), (14, 0), (14, 2), (12, 2)], 0, None,
           predefined="LANDING", parent=stair)
    sem = semantic_for(b.write(tmp_path / "joint_and_landing.ifc"))
    assert sem["ifc_semantic"]["summary"]["ignored_tiny_voids"] == 1
    assert not [o for o in sem["obstacles"] if o.get("type") == "walkable_void_mask"]
