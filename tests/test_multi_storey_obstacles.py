"""Walls/columns modelled once over several storeys must block every storey they cross.

Found in the first real .inpx (Revit advanced sample): 17 exterior/core walls
11.4 m high were placed only on level 1, so levels 2 and 3 had no wall there.
"""
from __future__ import annotations

from tests.engine_contract import engine_validate, requires_engine
from tests.ifc_factory import Building, add_opening, add_wall, semantic_for

H = 3.8


def _three_storeys() -> tuple[Building, list]:
    b = Building([0.0, H, 2 * H])
    for st, z in zip(b.storeys, (0.0, H, 2 * H)):
        b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], z, st)
    return b, b.storeys


def test_full_height_wall_and_column_are_copied_to_each_storey(tmp_path):
    b, (l1, l2, l3) = _three_storeys()
    wall = add_wall(b, 1.0, 5.0, 12.0, l1, height=3 * H)          # 11.4 m core wall
    gap = add_opening(b, wall, 4.0, 5.0, 5.0, 0.0, 2.1)             # opened gap on L1 only
    b.box("IfcColumn", 15, 2, 15.4, 2.4, 0.0, 3 * H, l1)            # 3-storey column
    add_wall(b, 1.0, 8.0, 6.0, l2, height=3.0)                      # ordinary wall: no copies
    sem = semantic_for(b.write(tmp_path / "tall.ifc"), {gap.GlobalId: "include"})

    core = [w for w in sem["walls"] if w["logical_wall_global_id"] == wall.GlobalId]
    by_level = {}
    for w in core:
        by_level.setdefault(w["level_key"], []).append(w)
    assert set(by_level) == {1, 2, 3}
    assert len(by_level[1]) == 2                                     # split by the L1 door
    assert len(by_level[2]) == len(by_level[3]) == 1                 # upper copies span the whole wall
    assert all(abs(w["height"] - H) < 1e-3 for w in core)            # no stacked 11.4 m obstacles
    assert all(w["z_offset"] == 0 for w in by_level[2] + by_level[3])

    cols = sem["columns"]
    assert sorted(c["level_key"] for c in cols) == [1, 2, 3]
    ordinary = [w for w in sem["walls"] if w["level_key"] == 2 and w["logical_wall_global_id"] != wall.GlobalId]
    assert len(ordinary) == 1 and "replicated_from_level" not in ordinary[0]

    keys = [o["key"] for k in ("areas", "walls", "columns", "obstacles", "vertical_connections") for o in sem[k]]
    assert len(keys) == len(set(keys))
    assert sem["ifc_semantic"]["summary"]["multi_storey_elements"] == 2
    assert any("span several storeys" in w for w in sem["ifc_semantic"]["warnings"])
    assert not any("without door gaps" in w for w in sem["ifc_semantic"]["warnings"])


def test_each_storey_gets_only_its_own_doors(tmp_path):
    b, (l1, l2, l3) = _three_storeys()
    wall = add_wall(b, 1.0, 5.0, 12.0, l1, height=3 * H)
    g1 = add_opening(b, wall, 4.0, 5.0, 5.0, 0.0, 2.1)              # L1 door
    g2 = add_opening(b, wall, 8.0, 9.0, 5.0, H, H + 2.1)            # L2 door
    win = add_opening(b, wall, 2.0, 3.0, 5.0, 2 * H + 1.2, 2 * H + 2.2)   # L3 window (sill 1.2 m)
    sem = semantic_for(b.write(tmp_path / "doors.ifc"),
                       {g.GlobalId: "include" for g in (g1, g2, win)})
    spans = {}
    for w in sem["walls"]:
        if w["logical_wall_global_id"] == wall.GlobalId:
            spans.setdefault(w["level_key"], []).append((w["start"][0], w["end"][0]))
    assert sorted(spans[1]) == [(1.0, 4.0), (5.0, 13.0)]       # only the L1 door
    assert sorted(spans[2]) == [(1.0, 8.0), (9.0, 13.0)]       # only the L2 door
    assert sorted(spans[3]) == [(1.0, 13.0)]                   # window above 1 m does not open L3


@requires_engine
def test_engine_accepts_replicated_obstacles(tmp_path):
    b, (l1, _, _) = _three_storeys()
    add_wall(b, 1.0, 5.0, 12.0, l1, height=3 * H)
    b.box("IfcColumn", 15, 2, 15.4, 2.4, 0.0, 3 * H, l1)
    sem = semantic_for(b.write(tmp_path / "tall.ifc"))
    result = engine_validate(sem, tmp_path)
    assert result["build_allowed"], result
    assert result["summary"]["vissim_obstacles"] == 6
