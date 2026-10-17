from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon, box

from ifc_vertical_service import (
    cluster_landing_levels,
    flight_profile,
    match_level,
)
from tests.ifc_factory import Building, semantic_for

FLOOR_L1 = [(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)]
STOREY_HEIGHT = 3.4


# ---------------------------------------------------------------------------
# Pure geometry helpers
# ---------------------------------------------------------------------------

def _wedge(x0, x1, y0, y1, z0, z1):
    pts = [
        (x0, y0, z0), (x1, y0, z0), (x1, y0, z1),
        (x0, y1, z0), (x1, y1, z0), (x1, y1, z1),
    ]
    flat = [c for p in pts for c in p]
    return flat, box(min(x0, x1), y0, max(x0, x1), y1)


@pytest.mark.parametrize("x0,x1", [(2.0, 6.0), (6.0, 2.0)])
def test_flight_profile_orients_polygon_bottom_edge_first(x0, x1):
    verts, footprint = _wedge(x0, x1, 1.0, 2.2, 0.0, 1.7)
    profile = flight_profile(verts, footprint)

    assert profile is not None
    assert math.isclose(profile["run_length"], 4.0, abs_tol=1e-6)
    assert math.isclose(profile["width"], 1.2, abs_tol=1e-6)
    assert math.isclose(profile["rise"], 1.7, abs_tol=1e-6)
    assert all(math.isclose(p[0], x0, abs_tol=1e-4) for p in profile["bottom_edge"])
    assert all(math.isclose(p[0], x1, abs_tol=1e-4) for p in profile["top_edge"])
    assert profile["polygon"][:2] == profile["bottom_edge"]
    assert profile["straightness"] > 0.99


def test_flight_profile_reports_non_straight_footprint():
    l_shape = Polygon([(0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (0, 1)])
    verts = [0, 0, 0, 4, 0, 0, 4, 4, 3, 3, 4, 3, 3, 1, 1, 0, 1, 0]
    profile = flight_profile(verts, l_shape)
    assert profile is not None
    assert profile["straightness"] < 0.85


def test_match_level_snaps_within_tolerance_and_reports_offset_otherwise():
    levels = [{"key": 1, "z": 0.0}, {"key": 2, "z": 3.4}]
    assert match_level(0.1, levels) == (1, 0.0, True)
    assert match_level(3.25, levels) == (2, 0.0, True)
    key, offset, exact = match_level(1.2, levels)
    assert (key, exact) == (1, False)
    assert math.isclose(offset, 1.2)


def test_cluster_landing_levels_dedupes_heights_and_skips_storey_heights():
    storeys = [{"key": 1, "z": 0.0}, {"key": 2, "z": 3.4}]
    result = cluster_landing_levels([1.70, 1.72, 3.38, 5.1], storeys)
    assert [lv["key"] for lv in result] == [901, 902]
    assert math.isclose(result[0]["z"], 1.71, abs_tol=1e-6)
    assert all(lv["generated"] for lv in result)


# ---------------------------------------------------------------------------
# End-to-end on synthetic IFC
# ---------------------------------------------------------------------------

def _two_storey() -> Building:
    b = Building([0.0, STOREY_HEIGHT])
    b.slab(FLOOR_L1, 0.0, b.storeys[0])
    b.slab(FLOOR_L1, STOREY_HEIGHT, b.storeys[1])
    return b


def test_stairs_are_review_only_by_default(tmp_path):
    b = _two_storey()
    stair = b.stair(b.storeys[0])
    b.flight(2.0, 8.0, 1.0, 2.2, 0.0, STOREY_HEIGHT, parent=stair)
    sem = semantic_for(b.write(tmp_path / "default.ifc"))
    assert sem["ifc_semantic"]["summary"]["vertical_connections"] == 0


def test_included_straight_stair_connects_storeys_from_geometry(tmp_path):
    b = _two_storey()
    stair = b.stair(b.storeys[0])
    flight = b.flight(2.0, 8.0, 1.0, 2.2, 0.0, STOREY_HEIGHT, parent=stair, NumberOfRisers=20)
    sem = semantic_for(b.write(tmp_path / "straight.ifc"), {stair.GlobalId: "include"})

    [conn] = sem["vertical_connections"]
    assert conn["type"] == "stairway"
    assert (conn["start_level"], conn["end_level"]) == (1, 2)
    assert conn["start_z_offset"] == 0.0 and conn["end_z_offset"] == 0.0
    assert conn["level_match"] == {"start": "exact", "end": "exact"}
    assert conn["ifc_global_id"] == flight.GlobalId
    assert conn["ifc_parent_global_id"] == stair.GlobalId
    assert conn["steps"] == 20 and conn["steps_source"] == "ifc_attribute"
    assert all(math.isclose(p[0], 2.0, abs_tol=1e-3) for p in conn["bottom_edge"])


def test_u_stair_creates_landing_level_and_two_flights(tmp_path):
    b = _two_storey()
    half = STOREY_HEIGHT / 2
    stair = b.stair(b.storeys[0])
    b.flight(2.0, 6.0, 1.0, 2.2, 0.0, half, parent=stair)
    b.flight(6.0, 2.0, 2.4, 3.6, half, STOREY_HEIGHT, parent=stair)
    landing = b.slab([(6.0, 1.0), (7.5, 1.0), (7.5, 3.6), (6.0, 3.6)], half, None,
                     predefined="LANDING", parent=stair)
    sem = semantic_for(b.write(tmp_path / "u.ifc"), {stair.GlobalId: "include"})
    summary = sem["ifc_semantic"]["summary"]

    assert summary["levels"] == 2
    assert summary["generated_landing_levels"] == 1
    landing_level = next(lv for lv in sem["levels"] if lv.get("generated"))
    assert landing_level["key"] == 901
    assert math.isclose(landing_level["z"], half, abs_tol=1e-3)

    landing_areas = [a for a in sem["areas"] if a["level_key"] == 901]
    assert len(landing_areas) == 1
    assert landing.GlobalId in landing_areas[0]["ifc_source_global_ids"]
    l1_areas = [a for a in sem["areas"] if a["level_key"] == 1]
    assert len(l1_areas) == 1
    assert math.isclose(Polygon(l1_areas[0]["polygon"]).area, 60.0, abs_tol=1e-3)

    links = sorted((c["start_level"], c["end_level"]) for c in sem["vertical_connections"])
    assert links == [(1, 901), (901, 2)]
    assert summary["vertical_ends_with_offset"] == 0


def test_flight_ending_off_level_uses_offset_and_warns(tmp_path):
    b = _two_storey()
    flight = b.flight(2.0, 5.0, 1.0, 2.2, 0.0, 1.2, storey=b.storeys[0])
    sem = semantic_for(b.write(tmp_path / "offset.ifc"), {flight.GlobalId: "include"})

    [conn] = sem["vertical_connections"]
    assert conn["start_level"] == 1 and conn["end_level"] == 1
    assert math.isclose(conn["end_z_offset"], 1.2, abs_tol=1e-3)
    assert conn["level_match"]["end"] == "offset"
    assert any("matches no storey or landing level" in w for w in sem["ifc_semantic"]["warnings"])


# ---------------------------------------------------------------------------
# Release gate: no silent omission / datum checks
# ---------------------------------------------------------------------------

def test_included_unmapped_element_is_reported(tmp_path):
    b = _two_storey()
    beam = b.box("IfcBeam", 1, 1, 5, 1.3, 3.0, 3.4, b.storeys[0])
    path = b.write(tmp_path / "beam.ifc")
    # Beams are excluded from the default geometry cache; force-include one.
    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model

    geometry = extract_ifc_geometry(path, mode="full")
    sem = build_semantic_model(path, geometry, {beam.GlobalId: "include"})
    assert any(beam.GlobalId in w and "not exported" in w for w in sem["ifc_semantic"]["warnings"])


def test_storey_elevation_vs_floor_top_mismatch_is_reported(tmp_path):
    b = Building([0.0, STOREY_HEIGHT])
    b.slab(FLOOR_L1, 0.3, b.storeys[0])
    sem = semantic_for(b.write(tmp_path / "datum.ifc"))
    assert any("differs from floor-slab tops" in w for w in sem["ifc_semantic"]["warnings"])
