from __future__ import annotations

import math

from shapely.geometry import Polygon

from ifc_semantic_service import classify_unfilled_opening, wall_footprint_solidity
from tests.ifc_factory import Building, add_opening, add_wall, semantic_for

FLOOR = [(0.0, 0.0), (12.0, 0.0), (12.0, 8.0), (0.0, 8.0)]


def _base() -> Building:
    b = Building([0.0, 3.4])
    b.slab(FLOOR, 0.0, b.storeys[0])
    return b


# --- pure helpers -----------------------------------------------------------

def test_classify_unfilled_opening():
    assert classify_unfilled_opening(0.9, 2.1, 0.0) == "passage_candidate"
    assert classify_unfilled_opening(1.2, 1.2, 0.9) == "not_passage"   # window-like
    assert classify_unfilled_opening(0.4, 2.1, 0.0) == "not_passage"   # too narrow


def test_solidity_separates_mitred_from_l_shaped_walls():
    mitred = Polygon([(0, 0), (1.0, 0), (0.8, 0.2), (0.2, 0.2)])
    l_shape = Polygon([(0, 0), (4, 0), (4, 0.2), (0.2, 0.2), (0.2, 3), (0, 3)])
    assert wall_footprint_solidity(mitred) > 0.99
    assert wall_footprint_solidity(l_shape) < 0.95


# --- unfilled openings ------------------------------------------------------

def test_unfilled_passage_is_reported_but_kept_closed_by_default(tmp_path):
    b = _base()
    wall = add_wall(b, 0.0, 4.0, 10.0, b.storeys[0])
    opening = add_opening(b, wall, 4.0, 5.0, 4.0, 0.0, 2.1)
    sem = semantic_for(b.write(tmp_path / "open.ifc"))
    ifc = sem["ifc_semantic"]

    [cand] = ifc["opening_candidates"]
    assert cand["global_id"] == opening.GlobalId
    assert cand["classification"] == "passage_candidate"
    assert not cand["applied"]
    assert math.isclose(cand["width"], 1.0, abs_tol=0.01)
    assert ifc["summary"]["unfilled_passage_candidates"] == 1
    assert ifc["summary"]["physical_wall_segments"] == 1
    assert any("look walkable" in w for w in ifc["warnings"])


def test_included_unfilled_opening_splits_wall(tmp_path):
    b = _base()
    wall = add_wall(b, 0.0, 4.0, 10.0, b.storeys[0])
    opening = add_opening(b, wall, 4.0, 5.0, 4.0, 0.0, 2.1)
    sem = semantic_for(b.write(tmp_path / "open.ifc"), {opening.GlobalId: "include"})
    ifc = sem["ifc_semantic"]

    assert ifc["summary"]["unfilled_openings_applied"] == 1
    assert ifc["summary"]["door_openings_applied"] == 0
    segments = sorted(sem["walls"], key=lambda w: w["start"][0])
    assert len(segments) == 2
    assert math.isclose(segments[0]["end"][0], 4.0, abs_tol=0.01)
    assert math.isclose(segments[1]["start"][0], 5.0, abs_tol=0.01)
    assert not any("look walkable" in w for w in ifc["warnings"])


def test_window_like_opening_is_not_a_passage(tmp_path):
    b = _base()
    wall = add_wall(b, 0.0, 4.0, 10.0, b.storeys[0])
    add_opening(b, wall, 4.0, 5.2, 4.0, 0.9, 2.1)
    ifc = semantic_for(b.write(tmp_path / "win.ifc"))["ifc_semantic"]
    [cand] = ifc["opening_candidates"]
    assert cand["classification"] == "not_passage"
    assert not any("look walkable" in w for w in ifc["warnings"])


# --- wall shapes ------------------------------------------------------------

def test_l_shaped_wall_becomes_polygon_obstacle_and_straight_wall_stays(tmp_path):
    b = _base()
    add_wall(b, 0.0, 1.0, 6.0, b.storeys[0])
    l_pts = [(8, 2), (11, 2), (11, 2.2), (8.2, 2.2), (8.2, 6), (8, 6)]
    verts = [(x, y, 0.0) for x, y in l_pts] + [(x, y, 3.0) for x, y in l_pts]
    n = len(l_pts)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    l_wall = b.mesh_element("IfcWall", verts, faces, storey=b.storeys[0])

    sem = semantic_for(b.write(tmp_path / "lwall.ifc"))
    ifc = sem["ifc_semantic"]

    assert ifc["summary"]["logical_walls"] == 2
    assert ifc["summary"]["polygon_walls"] == 1
    assert len(sem["walls"]) == 1
    [poly_wall] = [o for o in sem["obstacles"] if o.get("wall_shape") == "polygon"]
    assert poly_wall["ifc_global_id"] == l_wall.GlobalId
    assert math.isclose(Polygon(poly_wall["polygon"]).area, Polygon(l_pts).area, rel_tol=0.01)


def test_l_shaped_wall_with_opening_is_cut(tmp_path):
    b = _base()
    l_pts = [(1, 2), (9, 2), (9, 2.2), (1.2, 2.2), (1.2, 7), (1, 7)]
    verts = [(x, y, 0.0) for x, y in l_pts] + [(x, y, 3.0) for x, y in l_pts]
    n = len(l_pts)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    l_wall = b.mesh_element("IfcWall", verts, faces, storey=b.storeys[0])
    opening = add_opening(b, l_wall, 4.0, 5.0, 2.1, 0.0, 2.1)

    sem = semantic_for(b.write(tmp_path / "lcut.ifc"), {opening.GlobalId: "include"})
    parts = [o for o in sem["obstacles"] if o.get("wall_shape") == "polygon"]
    assert len(parts) == 2
    total = sum(Polygon(p["polygon"]).area for p in parts)
    assert math.isclose(total, Polygon(l_pts).area - 1.0 * 0.2, rel_tol=0.02)
