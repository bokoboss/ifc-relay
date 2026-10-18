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
    return r.json()


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
