"""Before build: block only what the Engine cannot build; everything else is a
Viswalk checklist item (the app converts IFC, it is not a BIM checker)."""
from __future__ import annotations

import pytest

from gate_service import evaluate_gate
from tests.engine_contract import engine_validate, requires_engine
from tests.ifc_factory import semantic_for
from tests.test_connectivity import _two_storeys


def _ids(gate, policy):
    return {i["id"] for i in gate["items"] if i["policy"] == policy}


CLEAN_CONNECTIVITY = {"zones": 1, "isolated_zones": [], "stairs_not_linked": []}


OK = {"issues": [], "severity_counts": {}, "build_allowed": True}


def test_only_engine_errors_block():
    sem = {"ifc_semantic": {"summary": {}, "warnings": [], "connectivity": CLEAN_CONNECTIVITY}}
    assert evaluate_gate(sem, None)["passed"]            # build validates again itself
    bad = {"issues": [{"type": "invalid_geometry", "key": 7, "severity": "error"}],
           "severity_counts": {"error": 1}, "build_allowed": False}
    gate = evaluate_gate(sem, bad)
    assert gate["blocked"] == ["engine_errors"] and not gate["passed"]


def test_failed_connectivity_and_skipped_edit_are_viswalk_checks():
    for con in ({"error": "ValueError: boom"}, None):     # a failed diagnostic is listed, never read as OK
        gate = evaluate_gate({"ifc_semantic": {"summary": {}, "warnings": [], "connectivity": con}}, OK)
        assert "connectivity_failed" in gate["to_check"] and gate["passed"]
    sem = {"ifc_semantic": {"summary": {}, "warnings": [], "connectivity": CLEAN_CONNECTIVITY,
                            "manual_edits": [{"id": "E1", "kind": "walkable"}],
                            "manual_edits_status": {"E1": {"applied": False, "reason": "no level at 1.90 m"}}}}
    gate = evaluate_gate(sem, OK)
    assert "manual_edits_skipped" in gate["to_check"] and gate["passed"]


@requires_engine
def test_isolated_room_is_a_viswalk_check_with_its_identity(tmp_path):
    from gate_service import checklist_markdown
    from tests.ifc_factory import add_wall

    b, ov = _two_storeys(with_stair=True)                    # closed room A in the L1 corner
    sem_a = semantic_for(b.write(tmp_path / "a.ifc"), ov)
    (tmp_path / "va").mkdir()
    gate_a = evaluate_gate(sem_a, engine_validate(sem_a, tmp_path / "va"))
    assert gate_a["passed"] and "isolated_zones" in _ids(gate_a, "check")

    b2, ov2 = _two_storeys(with_stair=True, room_door=True)  # room A opened, closed room B elsewhere
    l1 = b2.storeys[0]
    add_wall(b2, 0.0, 6.0, 6.0, l1)
    b2.box("IfcWall", 5.9, 6.0, 6.1, 10.0, 0.0, 3.0, l1)
    sem_b = semantic_for(b2.write(tmp_path / "b.ifc"), ov2)
    (tmp_path / "vb").mkdir()
    gate_b = evaluate_gate(sem_b, engine_validate(sem_b, tmp_path / "vb"))
    fp = {g["id"]: g["fingerprint"] for g in gate_a["items"]}
    item_b = next(i for i in gate_b["items"] if i["id"] == "isolated_zones")
    assert item_b["count"] == 1 and item_b["fingerprint"] != fp["isolated_zones"]   # same count, other room

    text = checklist_markdown(gate_b, "b.ifc", "b_viswalk.inpx", "2026-10-21T00:00:00")
    assert "- [ ] **" in text and "b.ifc" in text and item_b["identities"][0] in text


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
def test_build_goes_ahead_with_viswalk_checks(client, tmp_path, monkeypatch):
    import app as app_module

    calls = []

    def unavailable_builder(*args):
        calls.append("build")
        raise RuntimeError("Mock builder unavailable")

    monkeypatch.setattr(app_module, "build_vissim_model", unavailable_builder)
    b, ov = _two_storeys(with_stair=True)
    path = b.write(tmp_path / "api.ifc")
    with open(path, "rb") as fh:
        assert client.post("/api/import", files={"file": (path.name, fh)}).status_code == 200
    assert client.post("/api/analyze").status_code == 200
    for guid, status in ov.items():
        client.post("/api/selection", json={"global_id": guid, "status": status})
    assert client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []}).status_code == 200
    assert client.post("/api/ifc/semantic").status_code == 200
    assert client.post("/api/validate").status_code == 200
    gate = client.get("/api/gate").json()
    assert gate["passed"] and "isolated_zones" in gate["to_check"]
    assert client.post("/api/gate/ack", json={"id": "isolated_zones"}).status_code in (404, 405)   # no ack step

    r = client.post("/api/build-vissim")  # Checks allow reaching the builder on every platform, without COM.
    assert calls == ["build"]
    assert r.status_code == 500 and "Mock builder unavailable" in r.json()["detail"]


@requires_engine
def test_build_writes_viswalk_checklist(client, tmp_path, monkeypatch):
    import app as app_module

    def fake_build(app_dir, root, semantic_path, source_name):
        out = tmp_path / "api_viswalk.inpx"
        out.write_bytes(b"inpx")
        return {"output_path": str(out), "output_filename": out.name}

    monkeypatch.setattr(app_module, "build_vissim_model", fake_build)
    b, ov = _two_storeys(with_stair=True)
    path = b.write(tmp_path / "api.ifc")
    with open(path, "rb") as fh:
        client.post("/api/import", files={"file": (path.name, fh)})
    client.post("/api/analyze")
    for guid, status in ov.items():
        client.post("/api/selection", json={"global_id": guid, "status": status})
    client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []})
    client.post("/api/ifc/semantic")
    r = client.post("/api/build-vissim")
    assert r.status_code == 200, r.text
    import json
    manifest = json.loads((tmp_path / "api_build_manifest.json").read_text(encoding="utf-8"))
    assert any(c["id"] == "isolated_zones" for c in manifest["check_in_viswalk"])
    checklist = (tmp_path / "api_viswalk_checklist.md").read_text(encoding="utf-8")
    assert "พื้นที่ที่เดินไปไม่ถึง" in checklist and "api.ifc" in checklist


def test_all_closed_passage_candidates_reach_the_checklist():
    """ENG-01: no display cap on the list the checklist is built from."""
    import ifc_semantic_service

    assert not hasattr(ifc_semantic_service, "CANDIDATE_LIST_LIMIT")
    cands = [{"global_id": f"OP{n}", "classification": "passage_candidate", "decision": "auto"} for n in range(520)]
    sem = {"ifc_semantic": {"summary": {}, "warnings": [], "connectivity": CLEAN_CONNECTIVITY,
                            "opening_candidates": cands}}
    item = next(i for i in evaluate_gate(sem, OK)["items"] if i["id"] == "passages_closed")
    assert item["count"] == 520


def test_passage_that_cut_no_wall_is_a_viswalk_check():
    """ENG-02."""
    sem = {"ifc_semantic": {"summary": {}, "warnings": [], "connectivity": CLEAN_CONNECTIVITY,
                            "manual_edits": [{"id": "E1", "kind": "passage"}, {"id": "E2", "kind": "passage"}],
                            "manual_edits_status": {"E1": {"applied": True, "walls_cut": 0, "note": ""},
                                                    "E2": {"applied": True, "walls_cut": 1, "note": ""}}}}
    gate = evaluate_gate(sem, OK)
    item = next(i for i in gate["items"] if i["id"] == "manual_passage_no_effect")
    assert item["policy"] == "check" and item["identities"] == ["E1"] and gate["passed"]


@requires_engine
def test_result_of_an_older_generation_is_not_recorded(client, tmp_path):
    """ENG-03: Generate A -> validate A starts -> Generate B -> A's result is refused,
    and A's file is not overwritten by B."""
    import app as app_module
    from fastapi import HTTPException

    b, ov = _two_storeys(with_stair=True)
    path = b.write(tmp_path / "gen.ifc")
    with open(path, "rb") as fh:
        client.post("/api/import", files={"file": (path.name, fh)})
    client.post("/api/analyze")
    for guid, status in ov.items():
        client.post("/api/selection", json={"global_id": guid, "status": status})
    client.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []})
    client.post("/api/ifc/semantic")
    path_a = app_module.current_semantic_path_or_404()
    text_a = path_a.read_text(encoding="utf-8")
    client.post("/api/ifc/semantic")
    path_b = app_module.current_semantic_path_or_404()
    assert path_b != path_a and path_a.read_text(encoding="utf-8") == text_a
    with pytest.raises(HTTPException) as exc:
        app_module.commit_build_status(path_a, {"status": "validated"})
    assert exc.value.status_code == 409
    app_module.commit_build_status(path_b, {"status": "validated"})
    r = client.get("/api/ifc/semantic/download")
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('_gen_geometry_v03.json"')


def test_checklist_reads_codes_not_warning_text():
    """ARCH-01: rewording a warning cannot change the checklist."""
    sem = {"ifc_semantic": {"summary": {}, "connectivity": CLEAN_CONNECTIVITY,
                            "warnings": ["Tür XYZ hat keine Öffnung"],   # any wording
                            "diagnostics": [{"code": "door_not_converted", "ids": ["2O2Fr$t4X7Zf8NOew3FLOH"]},
                                            {"code": "multi_storey_no_doors", "ids": [], "count": 3}]}}
    items = {i["id"]: i for i in evaluate_gate(sem, OK)["items"]}
    assert items["doors_not_converted"]["identities"] == ["2O2Fr$t4X7Zf8NOew3FLOH"]
    assert items["multi_storey_no_doors"]["count"] == 3


@pytest.mark.parametrize("states,connected,pending,missing", [
    (["review", "review", "review"], False, 3, True),
    (["include", "review", "review"], True, 2, False),
    (["include", "exclude", "include"], True, 0, False),
    (["exclude", "exclude", "exclude"], False, 0, True),
    (["include", "include", "include"], False, 0, True),  # selection alone does not prove conversion
])
def test_c4_warnings_are_independent_nonblocking_checks(states, connected, pending, missing):
    sem = {"ifc_semantic": {"connectivity": CLEAN_CONNECTIVITY},
           "levels": [{"key": 1}, {"key": 2}],
           "areas": [{"level_key": k, "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]} for k in (1, 2)],
           "vertical_connections": ([{"key": 3001, "ifc_global_id": "built-flight",
                                      "level_match": {"start": "exact", "end": "exact"}}] if connected else [])}
    overview = {"units": [{"global_id": f"unit-{n}", "state": s} for n, s in enumerate(states)],
                "counts": {"flights": 9}}  # flight count never drives pending-unit count
    gate = evaluate_gate(sem, OK, overview)
    items = {i["id"]: i for i in gate["items"]}
    assert gate["passed"] and gate["blocked"] == []
    assert ("missing_vertical_connection" in items) is missing
    assert ("stair_review_pending" in items) is bool(pending)
    assert all(i["policy"] == "check" for i in gate["items"])
    if pending:
        assert items["stair_review_pending"]["count"] == pending
        assert set(items["stair_review_pending"]["identities"]) == {
            f"unit-{n}" for n, s in enumerate(states) if s == "review"}
    if missing:
        assert items["missing_vertical_connection"]["identities"] == ["L1", "L2"]


def test_c4_generated_landing_is_not_an_additional_storey():
    sem = {"ifc_semantic": {"connectivity": CLEAN_CONNECTIVITY},
           "levels": [{"key": 1}, {"key": 901, "generated": True}],
           "areas": [{"level_key": k, "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]} for k in (1, 901)]}
    assert "missing_vertical_connection" not in evaluate_gate(sem, OK)["to_check"]


def test_c4_mock_build_records_both_warnings_and_unit_ids(client, tmp_path, monkeypatch):
    import json
    import app as module
    from tests.test_stair_review import _model, _open, _prepare_gate

    calls = []

    def fake_build(*args):
        calls.append("build")
        out = tmp_path / "c4_viswalk.inpx"
        out.write_bytes(b"mock INPX; no COM invoked")
        return {"output_path": str(out), "output_filename": out.name}

    monkeypatch.setattr(module, "validate_engine_input", lambda *args: OK)
    monkeypatch.setattr(module, "build_vissim_model", fake_build)
    path, ids = _model(tmp_path, with_ramp=True)
    _open(client, path)
    _, expected = _prepare_gate(client)
    response = client.post("/api/build-vissim")
    assert response.status_code == 200, response.text
    assert calls == ["build"]
    manifest = json.loads((tmp_path / "c4_build_manifest.json").read_text(encoding="utf-8"))
    assert manifest["engineering_gate"] == expected
    assert manifest["viswalk_verified"] is False
    counts = {i["id"]: i["count"] for i in manifest["check_in_viswalk"]}
    assert counts["stair_review_pending"] == 3 and counts["missing_vertical_connection"] == 2
    checklist = (tmp_path / "c4_viswalk_checklist.md").read_text(encoding="utf-8")
    assert "บันได/ทางลาดที่ยังรอตรวจสอบ** (3)" in checklist
    assert "หลายชั้นแต่ไม่มีบันได/ทางลาดในโมเดลคนเดิน" in checklist
    assert all(ids[k] in checklist for k in ("parent", "loose", "ramp"))
