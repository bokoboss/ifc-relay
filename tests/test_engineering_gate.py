"""Engineering gate before build (P0-01): block / acknowledge / info."""
from __future__ import annotations

import pytest

from gate_service import evaluate_gate
from tests.engine_contract import engine_validate, requires_engine
from tests.ifc_factory import semantic_for
from tests.test_connectivity import _two_storeys


def _ids(gate, policy):
    return {i["id"] for i in gate["items"] if i["policy"] == policy}


CLEAN_CONNECTIVITY = {"zones": 1, "isolated_zones": [], "stairs_not_linked": []}


def test_not_validated_blocks():
    gate = evaluate_gate({"ifc_semantic": {"summary": {}, "warnings": [], "connectivity": CLEAN_CONNECTIVITY}}, None, {})
    assert gate["blocked"] == ["not_validated"] and not gate["passed"]


def test_failed_or_missing_connectivity_blocks():
    """F-02 / E2E-03: a diagnostic that failed is never read as 'all connected'."""
    for con in ({"error": "ValueError: boom"}, None):
        gate = evaluate_gate({"ifc_semantic": {"summary": {}, "warnings": [], "connectivity": con}},
                             {"issues": [], "severity_counts": {}, "build_allowed": True}, {})
        assert "connectivity_failed" in gate["blocked"] and not gate["passed"]


def test_skipped_manual_edit_blocks():
    """F-05: an edit the engineer drew but the model does not contain blocks the build."""
    sem = {"ifc_semantic": {"summary": {}, "warnings": [], "connectivity": CLEAN_CONNECTIVITY,
                            "manual_edits": [{"id": "E1", "kind": "walkable"}],
                            "manual_edits_status": {"E1": {"applied": False, "reason": "no level at 1.90 m"}}}}
    gate = evaluate_gate(sem, {"issues": [], "severity_counts": {}, "build_allowed": True}, {})
    assert "manual_edits_skipped" in gate["blocked"]


@requires_engine
def test_isolated_room_needs_acknowledgement_and_ack_is_tied_to_count(tmp_path):
    b, ov = _two_storeys(with_stair=True)
    sem = semantic_for(b.write(tmp_path / "g.ifc"), ov)
    validation = engine_validate(sem, tmp_path)
    gate = evaluate_gate(sem, validation, {})
    assert "isolated_zones" in _ids(gate, "ack")
    assert not gate["blocked"] and gate["pending_acknowledgement"] == ["isolated_zones"]
    assert not gate["passed"]

    from gate_service import record_ack
    item = next(i for i in gate["items"] if i["id"] == "isolated_zones")
    with pytest.raises(ValueError):
        record_ack({}, item, True, "")                     # reason required for this item
    acks = record_ack({}, item, True, "shaft")
    ok = evaluate_gate(sem, validation, acks)
    assert ok["passed"]
    done = next(i for i in ok["items"] if i["id"] == "isolated_zones")
    assert done["acknowledged"] and done["reason"] == "shaft"


@requires_engine
def test_ack_does_not_carry_over_to_a_different_problem_with_the_same_count(tmp_path):
    """F-01 / E2E-02: room A acknowledged; A fixed but room B appears -> pending again."""
    from gate_service import record_ack
    from tests.ifc_factory import add_wall

    b, ov = _two_storeys(with_stair=True)                    # closed room A in the L1 corner
    sem_a = semantic_for(b.write(tmp_path / "a.ifc"), ov)
    (tmp_path / "va").mkdir()
    val_a = engine_validate(sem_a, tmp_path / "va")
    gate_a = evaluate_gate(sem_a, val_a, {})
    acks = record_ack({}, next(i for i in gate_a["items"] if i["id"] == "isolated_zones"), True, "store room")
    assert evaluate_gate(sem_a, val_a, acks)["passed"]

    b2, ov2 = _two_storeys(with_stair=True, room_door=True)  # room A opened ...
    l1 = b2.storeys[0]
    add_wall(b2, 0.0, 6.0, 6.0, l1)                          # ... closed room B elsewhere
    b2.box("IfcWall", 5.9, 6.0, 6.1, 10.0, 0.0, 3.0, l1)
    sem_b = semantic_for(b2.write(tmp_path / "b.ifc"), ov2)
    assert len(sem_b["ifc_semantic"]["connectivity"]["isolated_zones"]) == 1   # same count as before
    (tmp_path / "vb").mkdir()
    val_b = engine_validate(sem_b, tmp_path / "vb")
    gate_b = evaluate_gate(sem_b, val_b, acks)
    assert "isolated_zones" in gate_b["pending_acknowledgement"] and not gate_b["passed"]


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
    assert client.post("/api/gate/ack", json={"id": "isolated_zones"}).status_code == 400   # reason required
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
    client.post("/api/gate/ack", json={"id": "isolated_zones", "reason": "closed room"})
    # page reload re-requests the 3D view
    assert client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []}).status_code == 200
    assert client.get("/api/gate").json()["passed"]
