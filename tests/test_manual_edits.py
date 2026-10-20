"""Manual plan edits (P1-02): added floor, obstacles and passages survive regeneration."""
from __future__ import annotations

import pytest

from tests.ifc_factory import semantic_for
from tests.test_connectivity import _two_storeys


def test_passage_opens_closed_room_and_obstacle_blocks(tmp_path):
    b, ov = _two_storeys(with_stair=True)          # closed room x 14..20, y 6..10 on L1
    path = b.write(tmp_path / "e.ifc")
    before = semantic_for(path, ov)["ifc_semantic"]["connectivity"]
    assert len(before["isolated_zones"]) == 1

    edits = [
        {"id": "E1", "kind": "passage", "level_key": 1, "polygon": [[13.5, 7.5], [14.5, 7.5], [14.5, 8.5], [13.5, 8.5]]},
        {"id": "E2", "kind": "obstacle", "level_key": 1, "polygon": [[3, 5], [5, 5], [5, 6], [3, 6]]},
        {"id": "E3", "kind": "walkable", "level_key": 1, "polygon": [[20, 0], [24, 0], [24, 4], [20, 4]]},
    ]
    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model
    sem = build_semantic_model(path, extract_ifc_geometry(path), ov, edits)
    info = sem["ifc_semantic"]
    assert info["manual_edits_applied"] == {"walkable": 1, "obstacle": 1, "passage": 1, "skipped": 0}
    assert not info["connectivity"]["isolated_zones"]                     # room reachable through E1
    cut = [w for w in sem["walls"] if w.get("manual_edit_id") == "E1"]
    assert len(cut) == 2                                                   # wall split into two pieces
    assert any(o.get("manual_edit_id") == "E2" and o["type"] == "manual_obstacle" for o in sem["obstacles"])
    assert any(a.get("manual_edit_id") == "E3" for a in sem["areas"])
    keys = [o["key"] for k in ("areas", "walls", "columns", "obstacles", "vertical_connections") for o in sem[k]]
    assert len(keys) == len(set(keys))


def test_bad_edit_is_skipped_with_warning(tmp_path):
    b, ov = _two_storeys(with_stair=False)
    path = b.write(tmp_path / "bad.ifc")
    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model
    sem = build_semantic_model(path, extract_ifc_geometry(path), ov,
                               [{"id": "E9", "kind": "walkable", "level_key": 77, "polygon": [[0, 0], [1, 0], [1, 1]]}])
    assert sem["ifc_semantic"]["manual_edits_applied"]["skipped"] == 1
    assert any("Manual edit E9 skipped" in w for w in sem["ifc_semantic"]["warnings"])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    from state_store import ProjectStateStore

    for name in ("UPLOAD_DIR", "SEMANTIC_DIR", "CACHE_DIR"):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(app_module, name, tmp_path / name)
    monkeypatch.setattr(app_module, "store", ProjectStateStore(tmp_path / "state.json"))
    return TestClient(app_module.app)


def test_edits_api_marks_model_stale_and_is_used_on_regenerate(client, tmp_path):
    b, ov = _two_storeys(with_stair=True)
    path = b.write(tmp_path / "api.ifc")
    with open(path, "rb") as fh:
        client.post("/api/import", files={"file": (path.name, fh)})
    client.post("/api/analyze")
    for guid, status in ov.items():
        client.post("/api/selection", json={"global_id": guid, "status": status})
    client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []})
    assert client.post("/api/ifc/semantic").status_code == 200

    r = client.post("/api/edits", json={"kind": "passage", "level_key": 1,
                                        "polygon": [[13.5, 7.5], [14.5, 7.5], [14.5, 8.5], [13.5, 8.5]]})
    assert r.status_code == 200 and r.json()["edit"]["id"] == "E1"
    assert client.get("/api/project").json()["semantic"]["stale"] is True
    assert client.post("/api/edits", json={"kind": "walkable", "level_key": 1, "polygon": [[0, 0], [0.01, 0], [0, 0.01]]}).status_code == 400

    client.post("/api/ifc/semantic")
    sem = client.get("/api/ifc/semantic").json()
    assert not sem["ifc_semantic"]["connectivity"]["isolated_zones"]
    assert client.delete("/api/edits/E1").status_code == 200
    assert client.get("/api/edits").json()["edits"] == []


def test_edit_rebinds_by_height_or_is_reported_skipped():
    from manual_edits import apply_manual_edits
    sq = [[0, 0], [2, 0], [2, 2], [0, 2]]
    edits = [
        {"id": "E1", "kind": "obstacle", "level_key": 901, "level_z": 1.9, "polygon": sq},   # landing renumbered
        {"id": "E2", "kind": "obstacle", "level_key": 902, "level_z": 5.7, "polygon": sq},   # landing gone
        {"id": "E3", "kind": "obstacle", "level_key": 1, "level_z": 0.0, "polygon": sq},
    ]
    obstacles, warnings, status = [], [], {}
    applied = apply_manual_edits(edits, areas=[], walls=[], obstacles=obstacles,
                                 level_z={1: 0.0, 2: 3.8, 903: 1.9}, warnings=warnings, status=status)
    assert status["E1"] == {"applied": True, "level_key": 903, "note": "re-bound from level 901 to level 903 by height 1.90 m"}
    assert status["E2"]["applied"] is False and "no level at 5.70 m" in status["E2"]["reason"]
    assert status["E3"]["applied"] is True and applied["skipped"] == 1
    assert sorted(o["level_key"] for o in obstacles) == [1, 903]


def test_invalid_polygons_are_rejected():
    from manual_edits import validate_edit
    assert validate_edit({"kind": "walkable", "polygon": [[0, 0], [1, 1], [1, 0], [0, 1]]}) == "polygon is self-intersecting"
    assert validate_edit({"kind": "walkable", "polygon": [[0, 0], [float("nan"), 0], [1, 1]]}) == "polygon has invalid coordinates"


def test_stale_model_cannot_be_exported(client, tmp_path):
    """F-03 / E2E-05: after an edit the old model is not handed out for the engine."""
    b, ov = _two_storeys(with_stair=True)
    path = b.write(tmp_path / "stale.ifc")
    with open(path, "rb") as fh:
        client.post("/api/import", files={"file": (path.name, fh)})
    client.post("/api/analyze")
    client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []})
    client.post("/api/ifc/semantic")
    assert client.get("/api/ifc/semantic/download").status_code == 200
    client.post("/api/edits", json={"kind": "obstacle", "level_key": 1, "polygon": [[3, 5], [5, 5], [5, 6], [3, 6]]})
    for url in ("/api/ifc/semantic", "/api/ifc/semantic/download", "/api/ifc/semantic/engine-download"):
        assert client.get(url).status_code == 409, url
    assert client.post("/api/ifc/semantic/export-engine-input").status_code == 409
    draft = client.get("/api/ifc/semantic?draft=1")
    assert draft.status_code == 200 and draft.json()["stale"] is True


def test_upload_size_limit(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VBB_MAX_UPLOAD_MB", "0.001")
    r = client.post("/api/import", files={"file": ("big.ifc", b"x" * 5000)})
    assert r.status_code == 413
    assert not any(p.name.endswith("big.ifc") for p in (tmp_path / "UPLOAD_DIR").iterdir())


def test_edit_review_states():
    from manual_edits import edit_review_state
    e = {"kind": "obstacle"}
    assert edit_review_state(e, None)["state"] == "pending"
    assert edit_review_state(e, {"applied": False, "reason": "no level at 5.70 m"}) == \
        {"state": "skipped", "detail": "no level at 5.70 m"}
    assert edit_review_state(e, {"applied": True, "level_key": 3, "note": "re-bound"})["state"] == "rebound"
    assert edit_review_state(e, {"applied": True, "level_key": 1, "note": ""})["state"] == "applied"
    assert edit_review_state({"kind": "passage"}, {"applied": True, "note": "", "walls_cut": 0})["state"] == "no_effect"
    assert edit_review_state({"kind": "passage"}, {"applied": True, "note": "", "walls_cut": 2})["state"] == "applied"


def test_edits_api_reports_review_state_per_edit(client, tmp_path):
    """F-19: each edit says what the last run did with it; a new edit is pending
    until regenerated, and a reused id does not inherit the deleted edit's result."""
    b, ov = _two_storeys(with_stair=True)
    path = b.write(tmp_path / "review.ifc")
    with open(path, "rb") as fh:
        client.post("/api/import", files={"file": (path.name, fh)})
    client.post("/api/analyze")
    for guid, status in ov.items():
        client.post("/api/selection", json={"global_id": guid, "status": status})
    client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []})
    assert client.post("/api/ifc/semantic").status_code == 200

    wall = [[13.5, 7.5], [14.5, 7.5], [14.5, 8.5], [13.5, 8.5]]
    open_floor = [[1, 1], [2, 1], [2, 2], [1, 2]]
    r = client.post("/api/edits", json={"kind": "passage", "level_key": 1, "polygon": wall})
    assert r.json()["edits"][0]["review"]["state"] == "pending"
    client.post("/api/edits", json={"kind": "passage", "level_key": 1, "polygon": open_floor})
    client.post("/api/ifc/semantic")
    states = {e["id"]: e["review"]["state"] for e in client.get("/api/edits").json()["edits"]}
    assert states == {"E1": "applied", "E2": "no_effect"}

    client.delete("/api/edits/E2")
    r = client.post("/api/edits", json={"kind": "obstacle", "level_key": 1, "polygon": open_floor})
    assert r.json()["edit"]["id"] == "E2"
    states = {e["id"]: e["review"]["state"] for e in r.json()["edits"]}
    assert states == {"E1": "applied", "E2": "pending"}
