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
    from manual_edits import polygon_fingerprint
    snapshots = info["manual_edits_snapshot"]
    assert [e["id"] for e in snapshots] == ["E1", "E2", "E3"]
    assert all(e["revision"] == 1 and e["shape_type"] == "polygon" for e in snapshots)
    assert [e["polygon_fingerprint"] for e in snapshots] == [
        polygon_fingerprint(edit["polygon"]) for edit in edits
    ]
    assert info["manual_edits_applied"] == {"walkable": 1, "obstacle": 1, "passage": 1, "exit": 0, "skipped": 0}
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


# ---- B1: revisioned, optimistic-lock geometry PATCH and guarded DELETE -------

def _b1_record(eid="E1", uid=None, *, shape_type="polygon", polygon=None, legacy=False):
    from uuid import uuid4

    record = {
        "id": eid,
        "uid": uid or uuid4().hex,
        "kind": "obstacle",
        "level_key": 1,
        "level_z": 0.0,
        "level_name": "Ground",
        "created_at": "2026-10-01T12:00:00",
        "note": "engineer annotation",
        "reviewer": "retained custom metadata",
        "polygon": polygon or [[0, 0], [2, 0], [2, 2], [0, 2]],
    }
    if not legacy:
        record.update({"revision": 1, "shape_type": shape_type})
    return record


def _b1_seed(client, tmp_path, edits, *, use_explicit_snapshot=False):
    """Synthetic semantic read-back, with no IFC parsing or Vissim dependency."""
    import json

    import app as app_module
    from manual_edits import edit_revision, edit_shape_type, polygon_fingerprint

    records = [{**e} for e in edits]
    info = {
        "manual_edits": records,
        "manual_edits_status": {
            e["id"]: {"applied": True, "level_key": 1, "note": ""} for e in records
        },
    }
    if use_explicit_snapshot:
        info["manual_edits_snapshot"] = [
            {
                "id": e["id"],
                "uid": e.get("uid") or e.get("created_at"),
                "revision": edit_revision(e),
                "shape_type": edit_shape_type(e),
                "polygon_fingerprint": polygon_fingerprint(e["polygon"]),
            }
            for e in records
        ]
    path = tmp_path / "b1-semantic.json"
    path.write_text(json.dumps({
        "levels": [{"key": 1, "z": 0.0, "name": "Ground"}],
        "ifc_semantic": info,
    }), encoding="utf-8")
    state = app_module.store.read()
    state["manual_edits"] = records
    state["semantic"] = {"status": "ready", "stale": False, "path": str(path)}
    state["build"] = {"status": "validated"}
    app_module.store.write(state)


def _b1_patch(client, record, polygon, *, uid=None, revision=None, shape_type=None):
    payload = {
        "expected_uid": uid if uid is not None else record["uid"],
        "expected_revision": revision if revision is not None else record.get("revision", 1),
        "polygon": polygon,
    }
    if shape_type is not None:
        payload["shape_type"] = shape_type
    return client.patch("/api/edits/" + record["id"], json=payload)


def test_b1_post_is_backward_compatible_and_persists_explicit_shapes(client, tmp_path):
    _b1_seed(client, tmp_path, [])
    square = [[0, 0], [2, 0], [2, 2], [0, 2]]
    old_post = client.post("/api/edits", json={
        "kind": "walkable", "level_key": 1, "polygon": square,
    })
    assert old_post.status_code == 200
    assert old_post.json()["edit"]["revision"] == 1
    assert old_post.json()["edit"]["shape_type"] == "polygon"

    rectangle = client.post("/api/edits", json={
        "kind": "obstacle", "level_key": 1, "polygon": square, "shape_type": "rectangle",
    })
    assert rectangle.status_code == 200
    assert rectangle.json()["edit"]["shape_type"] == "rectangle"
    bad_shape = client.post("/api/edits", json={
        "kind": "obstacle", "level_key": 1, "polygon": square, "shape_type": "triangle",
    })
    assert bad_shape.status_code == 422


def test_b1_patch_preserves_identity_sets_stale_and_only_changed_edit_pending(client, tmp_path):
    original = _b1_record()
    other = _b1_record("E2")
    _b1_seed(client, tmp_path, [original, other], use_explicit_snapshot=True)
    before = client.get("/api/edits").json()["edits"]
    assert [e["review"]["state"] for e in before] == ["applied", "applied"]

    new_polygon = [[0, 0], [3, 0], [3, 2], [0, 2]]
    result = _b1_patch(client, original, new_polygon)
    assert result.status_code == 200, result.text
    updated = result.json()["edit"]
    for field in ("id", "uid", "created_at", "kind", "level_key",
                  "level_z", "level_name", "note", "reviewer"):
        assert updated[field] == original[field]
    assert updated["polygon"] == new_polygon
    assert updated["shape_type"] == "polygon"
    assert updated["revision"] == 2
    assert updated["updated_at"]

    edits = result.json()["edits"]
    assert edits[0]["review"]["state"] == "pending"
    assert "รูปทรง" in edits[0]["review"]["detail"]
    assert edits[1]["review"]["state"] == "applied"
    assert [e["review"]["state"] for e in client.get("/api/edits").json()["edits"]] == [
        "pending", "applied",
    ]
    state = client.get("/api/project").json()
    assert state["semantic"]["stale"] is True
    assert state["build"]["status"] == "selection_changed"


def test_b1_same_geometry_patch_preserves_revision_stale_and_review(client, tmp_path):
    original = _b1_record()
    _b1_seed(client, tmp_path, [original], use_explicit_snapshot=True)
    for ring in (
        [[2, 0], [2, 2], [0, 2], [0, 0]],               # cyclic start
        [[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]],  # winding + closing point
    ):
        result = _b1_patch(client, original, ring)
        assert result.status_code == 200, result.text
        assert result.json()["edit"]["revision"] == 1
        assert result.json()["edit"]["polygon"] == original["polygon"]
        assert "updated_at" not in result.json()["edit"]
        assert result.json()["edits"][0]["review"]["state"] == "applied"
        state = client.get("/api/project").json()
        assert state["semantic"]["stale"] is False
        assert state["build"]["status"] == "validated"


@pytest.mark.parametrize("payload", [
    {"expected_revision": 1, "polygon": [[0, 0], [2, 0], [2, 2], [0, 2]]},
    {"expected_uid": "known", "polygon": [[0, 0], [2, 0], [2, 2], [0, 2]]},
    {"expected_uid": "known", "expected_revision": 1},
    {"expected_uid": "known", "expected_revision": 0, "polygon": [[0, 0], [2, 0], [2, 2], [0, 2]]},
    {"expected_uid": "known", "expected_revision": True, "polygon": [[0, 0], [2, 0], [2, 2], [0, 2]]},
    {"expected_uid": "known", "expected_revision": 1, "polygon": [["bad", 0], [2, 0], [2, 2]]},
    {"expected_uid": "known", "expected_revision": 1, "polygon": [[0, 0], [2, 0], [2, 2]], "shape_type": "ellipse"},
])
def test_b1_patch_schema_errors_422(client, tmp_path, payload):
    _b1_seed(client, tmp_path, [_b1_record()])
    response = client.patch("/api/edits/E1", json=payload)
    assert response.status_code == 422


def test_b1_conflicts_return_current_edit_and_do_not_mutate(client, tmp_path):
    original = _b1_record()
    _b1_seed(client, tmp_path, [original])
    polygon = [[0, 0], [3, 0], [3, 2], [0, 2]]
    for uid, revision in (("obsolete", 1), (original["uid"], 99)):
        response = _b1_patch(client, original, polygon, uid=uid, revision=revision)
        assert response.status_code == 409
        assert response.json()["detail"]["current_edit"]["uid"] == original["uid"]
        assert response.json()["detail"]["current_edit"]["revision"] == 1
    missing = client.patch("/api/edits/E999", json={
        "expected_uid": original["uid"], "expected_revision": 1, "polygon": polygon,
    })
    assert missing.status_code == 404
    state = client.get("/api/project").json()
    assert state["manual_edits"] == [original]
    assert state["semantic"]["stale"] is False


def test_b1_patch_rejects_invalid_geometry_and_shape_transitions(client, tmp_path):
    original = _b1_record()
    _b1_seed(client, tmp_path, [original])
    invalid = (
        [[0, 0], [2, 2], [2, 0], [0, 2]],   # self intersection
        [[0, 0], [0.001, 0], [0, 0.001]],  # tiny area
    )
    for polygon in invalid:
        assert _b1_patch(client, original, polygon).status_code == 400
    assert _b1_patch(client, original, original["polygon"], shape_type="rectangle").status_code == 400

    rectangle = _b1_record(shape_type="rectangle")
    _b1_seed(client, tmp_path, [rectangle])
    skew = [[0, 0], [2, 0], [2.15, 2], [0, 2]]
    assert _b1_patch(client, rectangle, skew).status_code == 400
    assert _b1_patch(client, rectangle, rectangle["polygon"], shape_type="rectangle").status_code == 400

    converted = _b1_patch(client, rectangle, skew, shape_type="polygon")
    assert converted.status_code == 200, converted.text
    assert converted.json()["edit"]["shape_type"] == "polygon"
    assert converted.json()["edit"]["revision"] == 2
    assert converted.json()["edits"][0]["review"]["state"] == "pending"


def test_b1_rectangle_tolerance_and_polygon_fingerprint():
    from manual_edits import polygon_fingerprint, validate_edit

    square = [[0, 0], [2, 0], [2, 2], [0, 2]]
    almost = [[0, 0], [2, 0], [2.0000001, 2], [0, 2]]
    skew = [[0, 0], [2, 0], [2.05, 2], [0, 2]]
    assert validate_edit({"kind": "obstacle", "polygon": square, "shape_type": "rectangle"}) is None
    assert validate_edit({"kind": "obstacle", "polygon": almost, "shape_type": "rectangle"}) is None
    assert "orthogonal" in validate_edit({
        "kind": "obstacle", "polygon": skew, "shape_type": "rectangle",
    })
    assert "orthogonal" in validate_edit({
        "kind": "obstacle", "polygon": [[0, 0], [2, 0], [1, 2]], "shape_type": "rectangle",
    })
    assert polygon_fingerprint(square) == polygon_fingerprint(
        [[2, 2], [2, 0], [0, 0], [0, 2], [2, 2]]
    )
    assert polygon_fingerprint(square) != polygon_fingerprint(
        [[0, 0], [3, 0], [3, 2], [0, 2]]
    )


def test_b1_legacy_edits_default_to_polygon_revision_one(client, tmp_path):
    original = _b1_record(legacy=True)
    _b1_seed(client, tmp_path, [original])  # old semantic JSON: raw edits only
    current = client.get("/api/edits").json()["edits"][0]
    assert (current["revision"], current["shape_type"]) == (1, "polygon")
    assert current["review"]["state"] == "applied"
    changed = _b1_patch(client, original, [[0, 0], [4, 0], [4, 2], [0, 2]])
    assert changed.status_code == 200
    assert changed.json()["edit"]["revision"] == 2
    assert changed.json()["edit"]["shape_type"] == "polygon"
    assert changed.json()["edits"][0]["review"]["state"] == "pending"


def test_b1_delete_preconditions_and_unguarded_legacy_delete(client, tmp_path):
    first, second = _b1_record(), _b1_record("E2")
    _b1_seed(client, tmp_path, [first, second])
    for params in (
        {"expected_uid": "wrong", "expected_revision": 1},
        {"expected_uid": first["uid"], "expected_revision": 2},
    ):
        conflict = client.delete("/api/edits/E1", params=params)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["current_edit"]["uid"] == first["uid"]
        assert client.get("/api/project").json()["semantic"]["stale"] is False
    bad_query = client.delete("/api/edits/E1", params={"expected_revision": 0})
    assert bad_query.status_code == 422
    valid = client.delete("/api/edits/E1", params={
        "expected_uid": first["uid"], "expected_revision": 1,
    })
    assert valid.status_code == 200
    assert [e["id"] for e in valid.json()["edits"]] == ["E2"]
    assert client.delete("/api/edits/E2").status_code == 200  # old UI
    assert client.delete("/api/edits/E2").status_code == 404


def test_b1_reused_e1_id_rejects_old_uid_after_delete_and_post(client, tmp_path):
    old = _b1_record("E1")
    _b1_seed(client, tmp_path, [old])
    deleted = client.delete("/api/edits/E1", params={
        "expected_uid": old["uid"], "expected_revision": 1,
    })
    assert deleted.status_code == 200
    created = client.post("/api/edits", json={
        "kind": "obstacle", "level_key": 1, "polygon": [[0, 0], [3, 0], [3, 2], [0, 2]],
    })
    assert created.status_code == 200, created.text
    replacement = created.json()["edit"]
    assert replacement["id"] == "E1"
    assert replacement["uid"] != old["uid"]
    response = _b1_patch(client, old, [[0, 0], [4, 0], [4, 2], [0, 2]])
    assert response.status_code == 409
    assert response.json()["detail"]["current_edit"]["uid"] == replacement["uid"]
    assert client.get("/api/project").json()["manual_edits"][0]["uid"] == replacement["uid"]


def test_b1_concurrent_patches_have_one_winner(client, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    original = _b1_record()
    _b1_seed(client, tmp_path, [original])
    polygon_a = [[0, 0], [3, 0], [3, 2], [0, 2]]
    polygon_b = [[0, 0], [4, 0], [4, 2], [0, 2]]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda ring: _b1_patch(client, original, ring), [polygon_a, polygon_b]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert client.get("/api/edits").json()["edits"][0]["revision"] == 2
