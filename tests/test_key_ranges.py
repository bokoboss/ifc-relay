from __future__ import annotations

from ifc_semantic_service import assign_key_ranges
from tests.ifc_factory import Building, semantic_for


def _items(n):
    return [{"name": f"x{i}"} for i in range(n)]


def test_small_model_keeps_v041_default_keys():
    cols = {"areas": _items(4), "walls": _items(29), "columns": _items(3),
            "obstacles": _items(2), "vertical_connections": _items(1)}
    ranges = assign_key_ranges(cols)
    assert ranges == {
        "areas": [1001, 1004],
        "walls": [1101, 1129],
        "columns": [1301, 1303],
        "obstacles": [1401, 1402],
        "vertical_connections": [2001, 2001],
    }


def test_large_model_keys_never_overlap_and_keep_order():
    cols = {"areas": _items(150), "walls": _items(2400), "columns": _items(700),
            "obstacles": _items(90), "vertical_connections": _items(60)}
    ranges = assign_key_ranges(cols)

    keys = [item["key"] for name in cols for item in cols[name]]
    assert len(keys) == len(set(keys))
    spans = sorted(ranges.values())
    assert all(a[1] < b[0] for a, b in zip(spans, spans[1:]))
    assert ranges["areas"] == [1001, 1150]
    assert ranges["walls"][0] == 2001          # pushed to the next free block
    assert [w["key"] for w in cols["walls"][:3]] == [2001, 2002, 2003]


def test_semantic_model_keys_are_unique_across_collections(tmp_path):
    b = Building([0.0, 3.4])
    for i in range(3):
        b.slab([(i * 20.0, 0), (i * 20.0 + 10, 0), (i * 20.0 + 10, 6), (i * 20.0, 6)], 0.0, b.storeys[0])
    b.box("IfcColumn", 2, 2, 2.4, 2.4, 0.0, 3.0, b.storeys[0])
    sem = semantic_for(b.write(tmp_path / "keys.ifc"))

    keys = [o["key"] for name in ("areas", "walls", "columns", "obstacles", "vertical_connections")
            for o in sem[name]]
    assert len(keys) == len(set(keys))
    assert sem["ifc_semantic"]["key_ranges"]["areas"] == [1001, 1003]
    assert sem["ifc_semantic"]["key_ranges"]["columns"] == [1301, 1301]
