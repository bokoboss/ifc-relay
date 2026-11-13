"""Landing coverage regressions, independent of project filenames and identities."""
from __future__ import annotations

import pytest
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from semantic_geometry import merge_walkable_components
from tests.ifc_factory import Building, semantic_for


def rotated_landings():
    return [translate(rotate(box(-1, -.95, 1, .95), angle), xoff=x, yoff=y)
            for x, y, angle in [(100, 40, 42), (-90, -40, 11),
                                (110, -65, -3), (-85, 25, 96)]]


@pytest.mark.parametrize("height_index", range(4))
def test_closing_preserves_each_disconnected_rotated_source(height_index):
    # Four intermediate planes, with two formerly disappearing components each.
    sources = [translate(p, yoff=height_index * 2.3) for p in rotated_landings()]
    output = unary_union(merge_walkable_components(sources))
    for source in sources:
        assert output.buffer(.005).covers(source)
        assert output.intersection(source).area / source.area > .99


def test_rotated_landing_metadata_has_real_spatial_contribution(tmp_path):
    b = Building([0, 4])
    stair = b.stair(b.storeys[0])
    sources = [(b.slab(list(p.exterior.coords)[:-1], 2, None,
                       predefined="LANDING", parent=stair), p) for p in rotated_landings()]
    sem = semantic_for(b.write(tmp_path / "rotated.ifc"))
    for slab, polygon in sources:
        areas = [a for a in sem["areas"] if slab.GlobalId in a.get("ifc_source_global_ids", [])]
        assert areas
        assert unary_union([Polygon(a["polygon"]) for a in areas]).buffer(.005).covers(polygon)
        assert all(Polygon(a["polygon"]).intersection(polygon).area > .001 for a in areas)


def test_landings_at_another_existing_storey_are_routed_to_its_floor(tmp_path):
    b = Building([0, 4])
    b.slab([(0, 0), (2, 0), (2, 2), (0, 2)], 4, b.storeys[1])
    stair = b.stair(b.storeys[0])
    sources = [(b.slab([(x, 0), (x + 1, 0), (x + 1, .7), (x, .7)], 4, None,
                       predefined="LANDING", parent=stair), box(x, 0, x + 1, .7))
               for x in (2, 8)]
    sem = semantic_for(b.write(tmp_path / "terminal.ifc"))
    assert not [lv for lv in sem["levels"] if lv.get("generated")]
    for slab, polygon in sources:
        areas = [a for a in sem["areas"] if slab.GlobalId in a.get("ifc_source_global_ids", [])]
        assert areas and all(a["level_key"] == 2 for a in areas)
        assert unary_union([Polygon(a["polygon"]) for a in areas]).buffer(.005).covers(polygon)
        assert all(Polygon(a["polygon"]).intersection(polygon).area > .001 for a in areas)
