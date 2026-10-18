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

def _model(tmp_path) -> tuple[Path, dict[str, str]]:
    b = Building([0.0, H])
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, b.storeys[0])
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], H, b.storeys[1])
    u = b.stair(b.storeys[0], name="U stair")
    f1 = b.flight(2.0, 6.0, 1.0, 2.2, 0.0, H / 2, parent=u)
    f2 = b.flight(6.0, 2.0, 2.4, 3.6, H / 2, H, parent=u)
    b.slab([(6, 1), (7.5, 1), (7.5, 3.6), (6, 3.6)], H / 2, None, predefined="LANDING", parent=u)
    loose = b.flight(12.0, 18.0, 5.0, 6.2, 0.0, H, storey=b.storeys[0])
    path = b.write(tmp_path / "stairs.ifc")
    return path, {"parent": u.GlobalId, "f1": f1.GlobalId, "f2": f2.GlobalId, "loose": loose.GlobalId}


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
        assert client.post("/api/import", files={"file": (path.name, fh)}).status_code == 200
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


# --- UI contract ----------------------------------------------------------------

def test_ui_wiring_for_stair_review():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    js3d = (ROOT / "static" / "app3d.js").read_text(encoding="utf-8")
    for el in ("stairBulkBtn", "stairConfirm", "stairConfirmBtn", "stairCancelBtn", "stairResetBtn",
               "stairUnits", "stairIncluded", "stairReview", "verticalSection", "verticalList"):
        assert f'id="{el}"' in html, el
    assert "/api/stairs/bulk" in js and "refreshStairOverview" in js
    assert "stairDirectionArrow" in js3d and "ConeGeometry" in js3d and "direction_status" in js3d
    assert "ยังไม่ถือว่ารับรองจนกว่าจะตรวจใน Vissim" in html
