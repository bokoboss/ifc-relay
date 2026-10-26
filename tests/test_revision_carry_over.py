from __future__ import annotations

import numpy as np
import pytest

from revision_service import compare_revisions, report_messages
from tests.ifc_factory import Building

FLOOR = [(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)]


def _revisions(tmp_path):
    """Revision A, then B with one element moved, one removed, one added."""
    b = Building([0.0, 3.4])
    keep = b.slab(FLOOR, 0.0, b.storeys[0])
    moved = b.slab(FLOOR, 3.4, b.storeys[1])
    removed = b.box("IfcColumn", 2, 2, 2.4, 2.4, 0.0, 3.0, b.storeys[0])
    rev_a = b.write(tmp_path / "rev_a.ifc")

    matrix = np.eye(4)
    matrix[0, 3] = 1.5
    matrix[2, 3] = 3.2
    b._run("geometry.edit_object_placement", product=moved, matrix=matrix)
    b._run("root.remove_product", product=removed)
    b.box("IfcColumn", 6, 2, 6.4, 2.4, 0.0, 3.0, b.storeys[0])
    rev_b = b.write(tmp_path / "rev_b.ifc")
    return rev_a, rev_b, keep.GlobalId, moved.GlobalId, removed.GlobalId


def test_compare_revisions_carries_drops_and_flags(tmp_path):
    rev_a, rev_b, keep, moved, removed = _revisions(tmp_path)
    overrides = {keep: "exclude", moved: "include", removed: "include"}

    carried, report = compare_revisions(rev_a, rev_b, overrides)

    assert carried == {keep: "exclude", moved: "include"}
    assert report["decisions"] == {"previous": 3, "carried": 2, "orphaned": 1, "changed": 1}
    assert report["orphaned"][0]["global_id"] == removed
    assert report["orphaned"][0]["ifc_type"] == "IfcColumn"
    [change] = report["changed"]
    assert change["global_id"] == moved and "placement" in change["changes"]
    assert report["products"]["added"] == 1 and report["products"]["removed"] == 1
    assert any("re-check" in line for line in report_messages(report))


def test_compare_revisions_without_previous_file_checks_existence_only(tmp_path):
    rev_a, rev_b, keep, moved, removed = _revisions(tmp_path)
    carried, report = compare_revisions(None, rev_b, {keep: "exclude", removed: "include"})
    assert carried == {keep: "exclude"}
    assert report["previous_file_available"] is False
    assert report["decisions"]["changed"] == 0


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_module
    from state_store import ProjectStateStore

    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(app_module, "store", ProjectStateStore(tmp_path / "state.json"))
    (tmp_path / "uploads").mkdir()
    return TestClient(app_module.app)


def _import(client, path, carry=True):
    with open(path, "rb") as fh:
        r = client.post("/api/import", files={"file": (path.name, fh)},
                        data={"carry_selection": "true" if carry else "false"})
    assert r.status_code == 200, r.text
    result = r.json()
    if result["status"] == "pending":
        response = client.post("/api/import/confirm", json={
            "pending_token": result["pending_token"],
            "expected_sha256": result["sha256"],
            "carry_manual_edits": False,
        })
        assert response.status_code == 200, response.text
        return response.json()
    return result


def test_api_reapplies_decisions_on_next_import(client, tmp_path):
    rev_a, rev_b, keep, moved, removed = _revisions(tmp_path)

    _import(client, rev_a)
    assert client.post("/api/analyze").status_code == 200
    for guid, status in ((keep, "exclude"), (moved, "include"), (removed, "include")):
        assert client.post("/api/selection", json={"global_id": guid, "status": status}).status_code == 200

    assert _import(client, rev_b)["carried_decisions_pending"] == 3
    audit = client.post("/api/analyze").json()
    assert audit["revision"]["decisions"]["carried"] == 2
    assert audit["warnings"][0].startswith("Revision carry-over")
    assert client.get("/api/selection").json()["overrides"] == {keep: "exclude", moved: "include"}
    assert client.get("/api/revision").json()["decisions"]["changed"] == 1

    # Re-running Analyze must not drop or re-diff decisions.
    client.post("/api/analyze")
    assert client.get("/api/selection").json()["overrides"] == {keep: "exclude", moved: "include"}


def test_api_can_start_fresh(client, tmp_path):
    rev_a, rev_b, keep, *_ = _revisions(tmp_path)
    _import(client, rev_a)
    client.post("/api/analyze")
    client.post("/api/selection", json={"global_id": keep, "status": "exclude"})

    assert _import(client, rev_b, carry=False)["carried_decisions_pending"] == 0
    client.post("/api/analyze")
    assert client.get("/api/selection").json()["overrides"] == {}
    assert client.get("/api/revision").status_code == 404


# ---- C3 Two-phase import + explicit manual carry consent ----------------------

def _c3_edits(client):
    """Use existing project state to isolate the import state transition."""
    import app as app_module

    records = [
        {"id": "E1", "uid": "persist-1", "revision": 2, "kind": "obstacle",
         "level_key": 1, "level_z": 0.0, "level_name": "L1",
         "polygon": [[0, 0], [2, 0], [2, 2], [0, 2]]},
        {"id": "E2", "uid": "persist-2", "revision": 1, "kind": "passage",
         "level_key": 1, "level_z": 0.0, "level_name": "L1",
         "polygon": [[3, 0], [4, 0], [4, 1], [3, 1]]},
    ]
    with app_module.store.lock:
        state = app_module.store.read()
        state["manual_edits"] = records
        state["semantic"] = {"status": "ready", "stale": False, "path": "old-model.json"}
        state["build"] = {"status": "validated"}
        app_module.store.write(state)
    return records


def _c3_pending(client, path, carry_selection=True):
    with open(path, "rb") as fh:
        response = client.post("/api/import", files={"file": (path.name, fh)},
                               data={"carry_selection": str(carry_selection).lower()})
    assert response.status_code == 200, response.text
    pending = response.json()
    assert pending["status"] == "pending"
    return pending


def _c3_confirm(client, pending, **options):
    return client.post("/api/import/confirm", json={
        "pending_token": pending["pending_token"],
        "expected_sha256": pending["sha256"],
        **options,
    })


def test_c3_t01_default_import_drops_old_manual_edits(client, tmp_path):
    rev_a, rev_b, keep, *_ = _revisions(tmp_path)
    _import(client, rev_a)
    old = _c3_edits(client)
    before = client.get("/api/project").json()
    pending = _c3_pending(client, rev_b)
    assert pending["manual_edit_count"] == 2
    assert pending["affected_levels"] == ["L1"]
    assert pending["carry_manual_edits"] is False
    assert client.get("/api/project").json() == before  # upload is not a commit
    response = _c3_confirm(client, pending)
    assert response.status_code == 200, response.text
    state = client.get("/api/project").json()
    assert state["manual_edits"] == []
    assert state["upload"]["original_name"] == rev_b.name
    assert state["semantic"] is None and state["build"]["status"] == "not_ready"


def test_c3_t02_explicit_same_project_manual_carry_after_confirmation(client, tmp_path):
    rev_a, rev_b, *_ = _revisions(tmp_path)
    _import(client, rev_a)
    edits = _c3_edits(client)
    pending = _c3_pending(client, rev_b)
    assert pending["identity"]["status"] in {"verified", "unverified"}
    assert client.get("/api/project").json()["manual_edits"] == edits
    without_risk = _c3_confirm(client, pending, carry_manual_edits=True)
    if pending["identity"]["status"] == "unverified":
        assert without_risk.status_code == 409
        response = _c3_confirm(client, pending, carry_manual_edits=True, acknowledge_unverified=True)
    else:
        response = without_risk
    assert response.status_code == 200, response.text
    assert client.get("/api/project").json()["manual_edits"] == edits


def test_c3_t03_different_project_guid_forbids_geometry_carry(client, tmp_path):
    rev_a, *_ = _revisions(tmp_path)
    other = Building([0.0, 3.4])
    other.slab(FLOOR, 0.0, other.storeys[0])
    path = other.write(tmp_path / "other.ifc")
    _import(client, rev_a)
    _c3_edits(client)
    pending = _c3_pending(client, path)
    assert pending["identity"]["status"] == "mismatch"
    assert "IfcProject.GlobalId" in " ".join(pending["identity"]["reasons"])
    before = client.get("/api/project").json()
    blocked = _c3_confirm(client, pending, carry_manual_edits=True, acknowledge_unverified=True)
    assert blocked.status_code == 409
    assert client.get("/api/project").json() == before
    assert _c3_confirm(client, pending, carry_manual_edits=False).status_code == 200
    assert client.get("/api/project").json()["manual_edits"] == []


def test_c3_t04_same_guid_but_coordinate_context_mismatch(client, tmp_path):
    import ifcopenshell

    a, b, *_ = _revisions(tmp_path)
    model = ifcopenshell.open(str(b))
    context = model.by_type("IfcGeometricRepresentationContext")[0]
    context.TrueNorth = model.createIfcDirection((0.0, 1.0))
    changed = tmp_path / "context_changed.ifc"
    model.write(str(changed))

    from revision_service import compare_project_identity, inspect_project_identity
    comparison = compare_project_identity(inspect_project_identity(a), inspect_project_identity(changed))
    assert comparison["status"] == "mismatch"
    assert "contexts" in " ".join(comparison["reasons"])

    _import(client, a)
    _c3_edits(client)
    pending = _c3_pending(client, changed)
    assert pending["identity"]["status"] == "mismatch"
    assert _c3_confirm(client, pending, carry_manual_edits=True, acknowledge_unverified=True).status_code == 409


def test_c3_t05_cancel_preserves_old_project_then_decline_without_reupload(client, tmp_path):
    a, b, *_ = _revisions(tmp_path)
    _import(client, a)
    _c3_edits(client)
    old = client.get("/api/project").json()
    pending = _c3_pending(client, b, carry_selection=False)
    cancelled = client.post("/api/import/cancel", json={
        "pending_token": pending["pending_token"], "expected_sha256": pending["sha256"],
    })
    assert cancelled.status_code == 200
    assert client.get("/api/project").json() == old
    assert _c3_confirm(client, pending).status_code == 409

    replacement = _c3_pending(client, b, carry_selection=False)
    assert _c3_confirm(client, replacement, carry_manual_edits=False).status_code == 200
    state = client.get("/api/project").json()
    assert state["manual_edits"] == []
    assert state["selection"]["overrides"] == {}


def test_c3_t06_superseded_token_and_upload_identity(client, tmp_path):
    a, b, *_ = _revisions(tmp_path)
    third = Building([0.0])
    third.slab(FLOOR, 0.0, third.storeys[0])
    c = third.write(tmp_path / "third.ifc")
    _import(client, a)
    first = _c3_pending(client, b)
    second = _c3_pending(client, c)
    assert _c3_confirm(client, first).status_code == 409
    assert _c3_confirm(client, second, expected_sha256="0" * 64).status_code == 409
    assert client.get("/api/project").json()["upload"]["original_name"] == a.name
    assert _c3_confirm(client, second).status_code == 200
    assert client.get("/api/project").json()["upload"]["original_name"] == c.name


def test_c3_expired_token_conflict_preserves_old_state(client, tmp_path, monkeypatch):
    import app as app_module

    a, b, *_ = _revisions(tmp_path)
    _import(client, a)
    old = client.get("/api/project").json()
    pending = _c3_pending(client, b)
    with app_module.store.lock:
        app_module._PENDING_IMPORT["expires_at"] = 0
    expired = _c3_confirm(client, pending)
    assert expired.status_code == 410
    assert client.get("/api/project").json() == old
    assert app_module._PENDING_IMPORT is None


def test_c3_failed_confirmation_after_concurrent_selection_change(client, tmp_path):
    import app as app_module

    a, b, *_ = _revisions(tmp_path)
    _import(client, a)
    _c3_edits(client)
    pending = _c3_pending(client, b)
    with app_module.store.lock:
        state = app_module.store.read()
        state["selection"]["overrides"]["new-guid"] = "exclude"
        app_module.store.write(state)
    before = client.get("/api/project").json()
    rejected = _c3_confirm(client, pending)
    assert rejected.status_code == 409
    assert client.get("/api/project").json() == before


def test_c3_rejects_invalid_file_with_existing_project(client, tmp_path):
    a, *_ = _revisions(tmp_path)
    _import(client, a)
    old = client.get("/api/project").json()
    bad = client.post("/api/import", files={"file": ("invalid.ifc", b"not an IFC")})
    assert bad.status_code == 400
    assert client.get("/api/project").json() == old


def test_c3_pending_file_bytes_tampered_same_size_rejected(client, tmp_path):
    from pathlib import Path
    import app as app_module

    a, b, *_ = _revisions(tmp_path)
    _import(client, a)
    pending = _c3_pending(client, b)
    old = client.get("/api/project").json()
    target = Path(app_module._PENDING_IMPORT["target"])
    with target.open("r+b") as fh:
        first = fh.read(1)
        fh.seek(0)
        fh.write(b"X" if first != b"X" else b"Y")
    result = _c3_confirm(client, pending)
    assert result.status_code == 409
    assert client.get("/api/project").json() == old


def test_c3_spatial_container_placement_change_blocks_manual_carry(tmp_path):
    import ifcopenshell
    import ifcopenshell.api
    import numpy as np

    first, second, *_ = _revisions(tmp_path)
    model = ifcopenshell.open(str(second))
    site = model.by_type("IfcSite")[0]
    matrix = np.eye(4)
    matrix[0, 3] = 8.0
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=site, matrix=matrix)
    changed = tmp_path / "site_translated.ifc"
    model.write(str(changed))

    from revision_service import inspect_project_identity, compare_project_identity
    old_id = inspect_project_identity(first)
    new_id = inspect_project_identity(changed)
    assert old_id["project_guid"] == new_id["project_guid"]
    assert old_id["sites"] == new_id["sites"]
    comparison = compare_project_identity(old_id, new_id)
    assert comparison["status"] == "mismatch"
    assert "spatial_placements" in " ".join(comparison["reasons"])


def test_c3_site_globalid_recreation_alone_does_not_count_as_coordinate_mismatch(tmp_path):
    import ifcopenshell
    import ifcopenshell.guid

    first, second, *_ = _revisions(tmp_path)
    model = ifcopenshell.open(str(second))
    site = model.by_type("IfcSite")[0]
    site.GlobalId = ifcopenshell.guid.new()
    changed = tmp_path / "site_guid_changed.ifc"
    model.write(str(changed))

    from revision_service import inspect_project_identity, compare_project_identity
    old_id = inspect_project_identity(first)
    new_id = inspect_project_identity(changed)
    assert old_id["project_guid"] == new_id["project_guid"]
    assert old_id["sites"] == new_id["sites"]
    assert old_id["spatial_placements"] == new_id["spatial_placements"]
    comparison = compare_project_identity(old_id, new_id)
    assert comparison["status"] != "mismatch"
