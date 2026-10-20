"""Core / review geometry tiers: slow review-rule elements load after the model."""
from __future__ import annotations

from ifc_geometry_service import extract_ifc_geometry
from ifc_semantic_service import build_semantic_model
from tests.ifc_factory import Building


def _model(tmp_path):
    b = Building([0.0, 3.4])
    l1, _ = b.storeys
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, l1)
    b.box("IfcColumn", 5, 5, 5.4, 5.4, 0.0, 3.0, l1)
    proxy = b.box("IfcBuildingElementProxy", 10, 5, 11, 6, 0.0, 1.0, l1)
    stair = b.stair(l1)
    b.flight(2.0, 8.0, 1.0, 2.2, 0.0, 3.4, parent=stair)
    return b.write(tmp_path / "tiers.ifc"), proxy


def _types(geom):
    return sorted({e["ifc_type"] for e in geom["elements"]})


def test_core_and_review_tiers_split_the_model(tmp_path):
    path, proxy = _model(tmp_path)
    core = extract_ifc_geometry(path, mode="simulation_relevant", tier="core")
    review = extract_ifc_geometry(path, mode="simulation_relevant", tier="review")
    full = extract_ifc_geometry(path, mode="simulation_relevant")
    assert "IfcBuildingElementProxy" not in _types(core)
    assert "IfcStairFlight" in _types(core)                      # stairs are not deferred
    assert _types(review) == ["IfcBuildingElementProxy"]
    assert core["element_count"] + review["element_count"] == full["element_count"]


def test_included_review_element_is_meshed_for_the_pedestrian_model(tmp_path):
    path, proxy = _model(tmp_path)
    geom = extract_ifc_geometry(path, mode="simulation_relevant", tier="core", extra_guids=[proxy.GlobalId])
    assert "IfcBuildingElementProxy" in _types(geom)
    sem = build_semantic_model(path, geom, {proxy.GlobalId: "include"})
    assert any(o.get("ifc_global_id") == proxy.GlobalId for o in sem["obstacles"])
