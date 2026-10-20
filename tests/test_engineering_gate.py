"""Engineering gate before build (P0-01): block / acknowledge / info."""
from __future__ import annotations

import pytest

from gate_service import evaluate_gate
from tests.engine_contract import engine_validate, requires_engine
from tests.ifc_factory import semantic_for
from tests.test_connectivity import _two_storeys


def _ids(gate, policy):
    return {i["id"] for i in gate["items"] if i["policy"] == policy}


def test_not_validated_blocks():
    gate = evaluate_gate({"ifc_semantic": {"summary": {}, "warnings": []}}, None, {})
    assert gate["blocked"] == ["not_validated"] and not gate["passed"]


@requires_engine
def test_isolated_room_needs_acknowledgement_and_ack_is_tied_to_count(tmp_path):
    b, ov = _two_storeys(with_stair=True)
    sem = semantic_for(b.write(tmp_path / "g.ifc"), ov)
    validation = engine_validate(sem, tmp_path)
    gate = evaluate_gate(sem, validation, {})
    assert "isolated_zones" in _ids(gate, "ack")
    assert not gate["blocked"] and gate["pending_acknowledgement"] == ["isolated_zones"]
    assert not gate["passed"]

    ok = evaluate_gate(sem, validation, {"isolated_zones": {"count": 1, "reason": "shaft"}})
    assert ok["passed"]
    item = next(i for i in ok["items"] if i["id"] == "isolated_zones")
    assert item["acknowledged"] and item["reason"] == "shaft"

    stale = evaluate_gate(sem, validation, {"isolated_zones": {"count": 2}})   # count changed -> re-ack
    assert not stale["passed"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    from state_store import ProjectStateStore

    for name in ("UPLOAD_DIR", "SEMANTIC_DIR", "CACHE_DIR"):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(app_module, name, tmp_path / name)
    monkeypatch.setattr(app_module, "store", ProjectStateStore(tmp_path / "state.json"))
    monkeypatch.setattr(app_module, "build_preflight", lambda base: [])
    return TestClient(app_module.app)


@requires_engine
def test_build_refused_until_acknowledged(client, tmp_path):
    b, ov = _two_storeys(with_stair=True)
    path = b.write(tmp_path / "api.ifc")
    with open(path, "rb") as fh:
        assert client.post("/api/import", files={"file": (path.name, fh)}).status_code == 200
    assert client.post("/api/analyze").status_code == 200
    for guid, status in ov.items():
        client.post("/api/selection", json={"global_id": guid, "status": status})
    assert client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []}).status_code == 200
    assert client.post("/api/ifc/semantic").status_code == 200

    r = client.post("/api/build-vissim")
    assert r.status_code == 409 and "ต้องกดรับทราบ" in r.json()["detail"]

    assert client.post("/api/validate").status_code == 200
    gate = client.get("/api/gate").json()
    assert gate["pending_acknowledgement"] == ["isolated_zones"]
    gate = client.post("/api/gate/ack", json={"id": "isolated_zones", "reason": "closed room"}).json()
    assert gate["passed"]

    r = client.post("/api/build-vissim")          # gate passes; COM build itself needs Windows
    assert r.status_code == 500 and "Windows" in r.json()["detail"]
    assert client.post("/api/gate/ack", json={"id": "engine_errors"}).status_code == 404


@requires_engine
def test_reloading_3d_keeps_validation_and_acks(client, tmp_path):
    b, ov = _two_storeys(with_stair=True)
    path = b.write(tmp_path / "reload.ifc")
    with open(path, "rb") as fh:
        client.post("/api/import", files={"file": (path.name, fh)})
    client.post("/api/analyze")
    for guid, status in ov.items():
        client.post("/api/selection", json={"global_id": guid, "status": status})
    client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []})
    client.post("/api/ifc/semantic")
    client.post("/api/validate")
    client.post("/api/gate/ack", json={"id": "isolated_zones"})
    # page reload re-requests the 3D view
    assert client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []}).status_code == 200
    assert client.get("/api/gate").json()["passed"]
