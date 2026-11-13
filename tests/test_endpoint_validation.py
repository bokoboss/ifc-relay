from __future__ import annotations

from connectivity_service import analyze_connectivity
from tests.test_engine_rectangles import _engine


def _model():
    return {"levels": [{"key": 1, "z": 0}, {"key": 2, "z": 3}],
            "areas": [{"key": 1, "level_key": 1, "polygon": [[3, 0], [6, 0], [6, 2], [3, 2]]},
                      {"key": 2, "level_key": 2, "polygon": [[9, 0], [12, 0], [12, 2], [9, 2]]}],
            "vertical_connections": [{"key": 3, "type": "stairway", "steps": 18,
                                      "start_level": 1, "end_level": 2,
                                      "polygon": [[0, 0], [0, 2], [10, 2], [10, 0]]}]}


def test_engine_checks_endpoint_strip_not_only_whole_ramp_overlap():
    engine = _engine()
    levels, areas, obstacles, vertical = engine.build_geometry_model(_model())
    warnings = engine.validate_model(levels, areas, obstacles, vertical)
    assert any(w["type"] == "vertical_connection_not_on_start_area" for w in warnings)


def test_engine_reports_end_on_level_without_any_area():
    engine = _engine()
    model = _model()
    model["areas"] = [a for a in model["areas"] if a["level_key"] == 1]
    warnings = engine.validate_model(*engine.build_geometry_model(model))
    assert any(w["type"] == "vertical_connection_not_on_end_area" for w in warnings)


def test_connectivity_does_not_bridge_a_nearby_gap():
    model = _model()
    model["areas"][0]["polygon"] = [[-.2, 0], [-.01, 0], [-.01, 10], [-.2, 10]]
    con = analyze_connectivity(model)
    assert con["stairs_linked"] == 0
    assert not con["stairs_not_linked"][0]["bottom_connected"]


def test_offset_end_does_not_connect_to_floor_at_another_height():
    engine = _engine()
    model = _model()
    model["vertical_connections"][0]["end_z_offset"] = -.5
    warnings = engine.validate_model(*engine.build_geometry_model(model))
    assert any(w["type"] == "vertical_connection_not_on_end_area"
               and w["reason"] == "endpoint_z_offset" for w in warnings)
