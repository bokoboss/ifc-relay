from __future__ import annotations

import json

from shapely.geometry import Polygon

from state_store import ProjectStateStore
from tests.ifc_factory import Building, semantic_for


def _ring_with_hole(b, storey, hx0, hy0, hx1, hy1):
    """Four slabs around a rectangular hole inside 0..10 x 0..10."""
    for poly in (
        [(0, 0), (10, 0), (10, hy0), (0, hy0)],
        [(0, hy1), (10, hy1), (10, 10), (0, 10)],
        [(0, hy0), (hx0, hy0), (hx0, hy1), (0, hy1)],
        [(hx1, hy0), (10, hy0), (10, hy1), (hx1, hy1)],
    ):
        b.slab(poly, 0.0, storey)


def test_tiny_slab_gap_gets_no_void_mask_but_is_reported(tmp_path):
    b = Building([0.0])
    _ring_with_hole(b, b.storeys[0], 5.0, 5.0, 5.1, 5.1)      # 0.01 m2
    sem = semantic_for(b.write(tmp_path / "gap.ifc"))
    ifc = sem["ifc_semantic"]
    assert ifc["summary"]["walkable_void_masks"] == 0
    assert ifc["summary"]["ignored_tiny_voids"] == 1
    assert any("slab-joint gaps" in w for w in ifc["warnings"])


def test_real_void_still_gets_mask(tmp_path):
    b = Building([0.0])
    _ring_with_hole(b, b.storeys[0], 4.0, 4.0, 6.0, 6.0)      # 4 m2 shaft
    sem = semantic_for(b.write(tmp_path / "void.ifc"))
    [mask] = [o for o in sem["obstacles"] if o.get("type") == "walkable_void_mask"]
    assert abs(Polygon(mask["polygon"]).area - 4.0) < 0.01


def test_state_store_write_is_atomic_and_leaves_no_temp(tmp_path):
    store = ProjectStateStore(tmp_path / "project_state.json")
    store.write({"a": 1})
    store.write({"a": 2, "text": "ทดสอบ"})
    assert json.loads((tmp_path / "project_state.json").read_text(encoding="utf-8"))["a"] == 2
    assert store.read()["text"] == "ทดสอบ"
    assert [p.name for p in tmp_path.iterdir()] == ["project_state.json"]
