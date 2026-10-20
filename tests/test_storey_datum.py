"""Storey walking datum must follow the main floor plate, not the number of slab pieces.

Regression for the Revit advanced sample (architectural IFC4): four small
FLOOR-typed sunscreen panels per storey sat 2.55 m above the floor and outvoted
the single floor plate, so every stair end missed its level by 2.55 m.
"""
from __future__ import annotations

from ifc_semantic_service import area_weighted_median
from tests.ifc_factory import Building, semantic_for

H = 3.8


def test_area_weighted_median_prefers_large_plate():
    assert area_weighted_median([(2.55, 1.0)] * 4 + [(0.0, 200.0)]) == 0.0
    assert area_weighted_median([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]) == 1.0


def test_small_high_floor_pieces_do_not_move_the_storey_datum(tmp_path):
    b = Building([0.0, H])
    l1, l2 = b.storeys
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, l1)
    for i in range(4):                                   # sunscreen panels, FLOOR type, +2.55 m
        b.slab([(20.5, 2 * i), (21.5, 2 * i), (21.5, 2 * i + 1), (20.5, 2 * i + 1)], 2.55, l1)
    b.slab([(0, 0), (20, 0), (20, 1), (0, 1)], H, l2)
    b.slab([(0, 2.2), (20, 2.2), (20, 10), (0, 10)], H, l2)
    b.slab([(0, 1), (2, 1), (2, 2.2), (0, 2.2)], H, l2)
    b.slab([(8, 1), (20, 1), (20, 2.2), (8, 2.2)], H, l2)
    stair = b.stair(l1)
    b.flight(2.0, 8.0, 1.0, 2.2, 0.0, H, parent=stair)
    sem = semantic_for(b.write(tmp_path / "datum.ifc"), {stair.GlobalId: "include"})
    warnings = sem["ifc_semantic"]["warnings"]
    assert not any("differs from floor-slab tops" in w for w in warnings), warnings
    vc = sem["vertical_connections"]
    assert len(vc) == 1
    assert (vc[0]["start_level"], vc[0]["end_level"]) == (1, 2)
    assert vc[0]["start_z_offset"] == 0 and vc[0]["end_z_offset"] == 0
    assert sum("+2.550 m from its storey floor" in w for w in warnings) == 4
