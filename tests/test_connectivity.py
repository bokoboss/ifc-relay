"""Pedestrian connectivity check (P1-04): zones nobody can reach are reported."""
from __future__ import annotations

from tests.ifc_factory import Building, add_opening, add_wall, semantic_for

H = 3.4


def _two_storeys(with_stair: bool = True, room_door: bool = False):
    b = Building([0.0, H])
    l1, l2 = b.storeys
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, l1)
    for poly in ([(0, 0), (20, 0), (20, 1), (0, 1)], [(0, 2.2), (20, 2.2), (20, 10), (0, 10)],
                 [(0, 1), (2, 1), (2, 2.2), (0, 2.2)], [(8, 1), (20, 1), (20, 2.2), (8, 2.2)]):
        b.slab(poly, H, l2)
    overrides = {}
    if with_stair:
        stair = b.stair(l1)
        b.flight(2.0, 8.0, 1.0, 2.2, 0.0, H, parent=stair)
        overrides[stair.GlobalId] = "include"
    # closed room in the L1 corner: x 14..20, y 6..10
    add_wall(b, 14.0, 6.0, 6.0, l1)
    w = b.box("IfcWall", 13.9, 6.0, 14.1, 10.0, 0.0, 3.0, l1)
    if room_door:
        gap = add_opening(b, w, 13.7, 14.3, 8.0, 0.0, 2.1)  # opening across the wall thickness
        overrides[gap.GlobalId] = "include"
    return b, overrides


def test_closed_room_and_missing_stair_are_reported(tmp_path):
    b, ov = _two_storeys(with_stair=False)
    sem = semantic_for(b.write(tmp_path / "a.ifc"), ov)
    con = sem["ifc_semantic"]["connectivity"]
    levels = sorted(z["level_key"] for z in con["isolated_zones"])
    # main network is the bigger floor; the other floor and the closed room are isolated
    assert con["networks"] == 3
    assert len(con["isolated_zones"]) == 2 and 1 in levels
    assert any(w.startswith("Connectivity: 2 walking zone(s)") for w in sem["ifc_semantic"]["warnings"])


def test_stair_links_floors_and_door_opens_room(tmp_path):
    b, ov = _two_storeys(with_stair=True)
    sem = semantic_for(b.write(tmp_path / "b.ifc"), ov)
    con = sem["ifc_semantic"]["connectivity"]
    assert con["stairs_linked"] == 1 and not con["stairs_not_linked"]
    assert con["main_network_levels"] == [1, 2]
    assert len(con["isolated_zones"]) == 1                      # only the closed room
    assert con["isolated_zones"][0]["level_key"] == 1
    assert 20 < con["isolated_zones"][0]["area_m2"] < 26

    b2, ov2 = _two_storeys(with_stair=True, room_door=True)
    sem2 = semantic_for(b2.write(tmp_path / "c.ifc"), ov2)
    con2 = sem2["ifc_semantic"]["connectivity"]
    assert con2["networks"] == 1 and not con2["isolated_zones"]
    assert not any(w.startswith("Connectivity:") for w in sem2["ifc_semantic"]["warnings"])
