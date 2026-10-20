"""IFC type FLOOR alone is not proof that a slab is walkable (P0-02).

Revit sample: 'Metal Sunscreen' panels are FLOOR slabs 2.55 m above the floor and
were merged into the walkable floor. Far off-level slabs now stay out until the
engineer includes them; small steps / sunken wet areas are still merged with a warning.
"""
from __future__ import annotations

from shapely.geometry import Polygon
from shapely.ops import unary_union

from tests.ifc_factory import Building, semantic_for

H = 3.8


def _walkable(sem, level):
    return unary_union([Polygon(a["polygon"]) for a in sem["areas"] if a["level_key"] == level])


def _model():
    b = Building([0.0, H])
    l1, l2 = b.storeys
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, l1)
    sun = b.slab([(21, 0), (22, 0), (22, 10), (21, 10)], 2.55, l1)          # sunscreen
    wet = b.slab([(-4, 0), (0, 0), (0, 3), (-4, 3)], -0.27, l1)             # sunken toilet
    mezz = b.slab([(0, 11), (6, 11), (6, 15), (0, 15)], 1.5, l1)            # mezzanine
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], H, l2)
    return b, sun, wet, mezz


def test_far_off_level_slabs_wait_for_review(tmp_path):
    b, sun, wet, mezz = _model()
    sem = semantic_for(b.write(tmp_path / "m.ifc"))
    floor = _walkable(sem, 1)
    assert floor.contains(Polygon([(-3.9, 0.1), (-0.1, 0.1), (-0.1, 2.9)]))        # sunken area merged
    assert not floor.intersects(Polygon([(21.1, 0.1), (21.9, 0.1), (21.9, 9.9)]))  # sunscreen out
    assert not floor.intersects(Polygon([(0.1, 11.1), (5.9, 11.1), (5.9, 14.9)]))  # mezzanine out
    info = sem["ifc_semantic"]
    out = {x["global_id"]: x for x in info["off_level_slabs"]}
    assert set(out) == {sun.GlobalId, mezz.GlobalId}
    assert out[sun.GlobalId]["decision"] == "auto" and abs(out[sun.GlobalId]["offset_m"] - 2.55) < 1e-3
    assert info["summary"]["off_level_slabs_excluded"] == 2
    assert sum("left out of level 1" in w for w in info["warnings"]) == 2
    assert sum("merged into level 1" in w for w in info["warnings"]) == 1


def test_engineer_can_include_an_off_level_slab(tmp_path):
    """An included mezzanine becomes its own level at its real height."""
    b, sun, wet, mezz = _model()
    sem = semantic_for(b.write(tmp_path / "m.ifc"), {mezz.GlobalId: "include"})
    floor = _walkable(sem, 1)
    assert not floor.intersects(Polygon([(0.1, 11.1), (5.9, 11.1), (5.9, 14.9)]))
    [lv] = [lv for lv in sem["levels"] if str(lv["name"]).startswith("Mezzanine")]
    assert abs(lv["z"] - 1.5) < 1e-3 and lv["key"] >= 901
    assert _walkable(sem, lv["key"]).intersects(Polygon([(0.1, 11.1), (5.9, 11.1), (5.9, 14.9)]))
    assert any("included as its own level (mezzanine)" in w for w in sem["ifc_semantic"]["warnings"])
    out = {x["global_id"]: x["decision"] for x in sem["ifc_semantic"]["off_level_slabs"]}
    assert out == {sun.GlobalId: "auto", mezz.GlobalId: "include"}
    assert sem["ifc_semantic"]["summary"]["off_level_slabs_excluded"] == 1
