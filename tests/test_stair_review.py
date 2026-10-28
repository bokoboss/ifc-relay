from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

from ifc_vertical_service import direction_assessment, flight_profile
from tests.ifc_factory import Building

H = 3.4
ROOT = Path(__file__).resolve().parent.parent


# --- direction assessment ---------------------------------------------------

def _wedge(x0, x1, y0, y1, z0, z1):
    pts = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y1, z0), (x1, y1, z0), (x1, y1, z1)]
    return [c for p in pts for c in p], box(min(x0, x1), y0, max(x0, x1), y1)


def test_straight_wedge_direction_is_derived():
    verts, fp = _wedge(2, 8, 1, 2.2, 0, H)
    assert direction_assessment(flight_profile(verts, fp))[0] == "derived_from_geometry"


def test_block_with_equal_end_heights_needs_review():
    pts = [(0, 0, 0), (6, 0, 0), (6, 1.2, 0), (0, 1.2, 0), (0, 0, H), (6, 0, H), (6, 1.2, H), (0, 1.2, H)]
    verts = [c for p in pts for c in p]
    status, reason = direction_assessment(flight_profile(verts, box(0, 0, 6, 1.2)))
    assert status == "needs_review" and "similar heights" in reason


def test_non_straight_footprint_needs_review():
    l_shape = Polygon([(0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (0, 1)])
    verts = [0, 0, 0, 4, 0, 0, 4, 4, 3, 3, 4, 3, 3, 1, 1, 0, 1, 0]
    assert direction_assessment(flight_profile(verts, l_shape))[0] == "needs_review"


# --- bulk include through the API -------------------------------------------

def _model(tmp_path, *, with_ramp=False) -> tuple[Path, dict[str, str]]:
    b = Building([0.0, H])
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, b.storeys[0])
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], H, b.storeys[1])
    u = b.stair(b.storeys[0], name="U stair")
    f1 = b.flight(2.0, 6.0, 1.0, 2.2, 0.0, H / 2, parent=u)
    f2 = b.flight(6.0, 2.0, 2.4, 3.6, H / 2, H, parent=u)
    b.slab([(6, 1), (7.5, 1), (7.5, 3.6), (6, 3.6)], H / 2, None, predefined="LANDING", parent=u)
    loose = b.flight(12.0, 18.0, 5.0, 6.2, 0.0, H, storey=b.storeys[0])
    ids = {"parent": u.GlobalId, "f1": f1.GlobalId, "f2": f2.GlobalId, "loose": loose.GlobalId}
    if with_ramp:
        ramp = b._run("root.create_entity", ifc_class="IfcRamp", name="Review ramp")
        b._run("spatial.assign_container", relating_structure=b.storeys[0], products=[ramp])
        b.mesh_element("IfcRampFlight",
                       [(12, 7, 0), (18, 7, 0), (18, 7, H), (12, 8.2, 0), (18, 8.2, 0), (18, 8.2, H)],
                       [(0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (1, 4, 5, 2), (0, 2, 5, 3)], parent=ramp)
        ids["ramp"] = ramp.GlobalId
    path = b.write(tmp_path / "stairs.ifc")
    return path, ids


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_module
    from state_store import ProjectStateStore

    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(app_module, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(app_module, "SEMANTIC_DIR", tmp_path / "semantic")
    monkeypatch.setattr(app_module, "store", ProjectStateStore(tmp_path / "state.json"))
    for d in ("uploads", "cache", "semantic"):
        (tmp_path / d).mkdir()
    return TestClient(app_module.app)


def _open(client, path):
    with open(path, "rb") as fh:
        response = client.post("/api/import", files={"file": (path.name, fh)}, data={"carry_selection": "false"})
        assert response.status_code == 200, response.text
    pending = response.json()
    if pending["status"] == "pending":
        confirmed = client.post("/api/import/confirm", json={"pending_token": pending["pending_token"],
                                "expected_sha256": pending["sha256"], "carry_manual_edits": False})
        assert confirmed.status_code == 200, confirmed.text
    assert client.post("/api/analyze").status_code == 200
    assert client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []}).status_code == 200


def test_overview_counts_units_without_double_counting(client, tmp_path):
    path, ids = _model(tmp_path)
    _open(client, path)
    ov = client.get("/api/stairs").json()
    assert ov["counts"] == {"units": 2, "flights": 3, "include": 0, "review": 2, "exclude": 0}
    assert {u["global_id"] for u in ov["units"]} == {ids["parent"], ids["loose"]}


def test_bulk_include_marks_units_and_converts_each_flight_once(client, tmp_path):
    path, ids = _model(tmp_path)
    _open(client, path)
    res = client.post("/api/stairs/bulk", json={"status": "include"}).json()
    overrides = res["selection"]["overrides"]
    assert overrides == {g: "include" for g in (ids["parent"], ids["f1"], ids["f2"], ids["loose"])}
    assert res["overview"]["counts"]["include"] == 2 and res["overview"]["counts"]["review"] == 0

    sem = client.post("/api/ifc/semantic").json()["model"]
    guids = [v["ifc_global_id"] for v in sem["vertical_connections"]]
    assert sorted(guids) == sorted([ids["f1"], ids["f2"], ids["loose"]])  # no parent+child duplicates
    assert all(v["direction_status"] == "derived_from_geometry" for v in sem["vertical_connections"])
    assert all(v["direction_certified"] is False for v in sem["vertical_connections"])


def test_explicitly_excluded_child_flight_stays_excluded(client, tmp_path):
    path, ids = _model(tmp_path)
    _open(client, path)
    client.post("/api/selection", json={"global_id": ids["f2"], "status": "exclude"})
    client.post("/api/stairs/bulk", json={"status": "include"})
    sem = client.post("/api/ifc/semantic").json()["model"]
    guids = {v["ifc_global_id"] for v in sem["vertical_connections"]}
    assert ids["f2"] not in guids and ids["f1"] in guids


def test_bulk_auto_returns_stairs_to_review(client, tmp_path):
    path, ids = _model(tmp_path)
    _open(client, path)
    client.post("/api/stairs/bulk", json={"status": "include"})
    client.post("/api/selection", json={"global_id": ids["f1"], "status": "include"})
    res = client.post("/api/stairs/bulk", json={"status": "auto"}).json()
    assert res["selection"]["overrides"] == {}
    assert res["overview"]["counts"]["review"] == 2


def _prepare_gate(client):
    response = client.post("/api/ifc/semantic")
    assert response.status_code == 200, response.text
    gate = client.get("/api/gate")
    assert gate.status_code == 200, gate.text
    return response.json()["model"], gate.json()


def test_c4_three_review_units_then_partial_include_then_all_decided(client, tmp_path):
    path, ids = _model(tmp_path, with_ramp=True)
    _open(client, path)
    overview = client.get("/api/stairs").json()
    assert overview["counts"] == {"units": 3, "flights": 4, "include": 0, "review": 3, "exclude": 0}
    _, gate = _prepare_gate(client)
    items = {i["id"]: i for i in gate["items"]}
    pending = items["stair_review_pending"]
    assert pending["count"] == 3
    assert set(pending["identities"]) == {ids["parent"], ids["loose"], ids["ramp"]}
    assert "missing_vertical_connection" in gate["to_check"] and gate["passed"]

    assert client.post("/api/selection", json={"global_id": ids["loose"], "status": "include"}).status_code == 200
    assert client.get("/api/gate").status_code == 400  # old generation is never presented as current
    sem, partial = _prepare_gate(client)
    assert [v["ifc_global_id"] for v in sem["vertical_connections"]] == [ids["loose"]]
    item = next(i for i in partial["items"] if i["id"] == "stair_review_pending")
    assert item["count"] == 2 and set(item["identities"]) == {ids["parent"], ids["ramp"]}
    assert item["fingerprint"] != pending["fingerprint"]
    assert "missing_vertical_connection" not in partial["to_check"] and partial["passed"]

    for guid in (ids["parent"], ids["ramp"]):
        assert client.post("/api/selection", json={"global_id": guid, "status": "exclude"}).status_code == 200
    _, decided = _prepare_gate(client)
    assert "stair_review_pending" not in decided["to_check"]
    assert "missing_vertical_connection" not in decided["to_check"] and decided["passed"]


def test_c4_overview_cache_follows_selection_and_ifc_revision(client, tmp_path, monkeypatch):
    import app as module

    calls = []
    run = module.model_jobs.run

    def tracked(label, *args, **kwargs):
        if label == "stairs":
            calls.append(label)
        return run(label, *args, **kwargs)

    monkeypatch.setattr(module.model_jobs, "run", tracked)
    path, ids = _model(tmp_path, with_ramp=True)
    _open(client, path)
    overview = client.get("/api/stairs").json()
    _, gate = _prepare_gate(client)
    for _ in range(3):
        assert client.get("/api/gate").json() == gate
        assert client.get("/api/stairs").json() == overview
    assert len(calls) == 1  # Gate and Overview share the same parsed summary

    client.post("/api/selection", json={"global_id": ids["parent"], "status": "exclude"})
    _, updated = _prepare_gate(client)
    assert next(i for i in updated["items"] if i["id"] == "stair_review_pending")["count"] == 2
    assert len(calls) == 2

    revised_path, new_ids = _model(tmp_path, with_ramp=True)
    _open(client, revised_path)
    assert client.get("/api/gate").status_code == 404  # confirmed import clears the old semantic model
    _, revised = _prepare_gate(client)
    new_item = next(i for i in revised["items"] if i["id"] == "stair_review_pending")
    assert new_item["count"] == 3
    assert set(new_item["identities"]) == {new_ids["parent"], new_ids["loose"], new_ids["ramp"]}
    assert set(new_item["identities"]).isdisjoint(ids.values())
    assert len(calls) == 3


@pytest.mark.parametrize("elevations", [[0.0], [0.0, H]])
def test_c4_single_used_storey_does_not_warn_about_missing_connection(client, tmp_path, elevations):
    b = Building(elevations)  # an unused storey record is not an active floor
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, b.storeys[0])
    _open(client, b.write(tmp_path / "one_floor.ifc"))
    _, gate = _prepare_gate(client)
    assert "missing_vertical_connection" not in gate["to_check"]
    assert "stair_review_pending" not in gate["to_check"] and gate["passed"]


# --- UI contract ----------------------------------------------------------------

def test_ui_wiring_for_stair_review():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    from tests.ui_sources import app_js
    js = app_js()
    js3d = (ROOT / "static" / "app3d.js").read_text(encoding="utf-8")
    for el in ("stairBulkBtn", "stairConfirm", "stairConfirmBtn", "stairCancelBtn", "stairResetBtn",
               "stairUnits", "stairIncluded", "stairReview", "verticalSection", "verticalList"):
        assert f'id="{el}"' in html, el
    assert "/api/stairs/bulk" in js and "refreshStairOverview" in js
    assert "stairDirectionArrow" in js3d and "ConeGeometry" in js3d and "direction_status" in js3d
    assert "ยังไม่ถือว่ารับรองจนกว่าจะตรวจใน Vissim" in html
