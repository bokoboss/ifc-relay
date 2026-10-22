"""PERF-01: the 12,000-element guard is for the browser view only; preparing the
pedestrian model uses its own, higher ceiling."""
from __future__ import annotations

import pytest


def test_semantic_preparation_uses_its_own_ceiling(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    from state_store import ProjectStateStore
    from tests.ifc_factory import Building

    for name in ("UPLOAD_DIR", "SEMANTIC_DIR", "CACHE_DIR"):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(app_module, name, tmp_path / name)
    monkeypatch.setattr(app_module, "store", ProjectStateStore(tmp_path / "state.json"))
    seen = {}
    real = app_module.model_jobs.run

    def spy(label, target, *args, **kwargs):
        if label in ("geometry", "semantic"):
            ceiling = (kwargs.get("geometry_kwargs") or kwargs).get("max_elements")
            seen.setdefault("calls", []).append(ceiling)
        return real(label, target, *args, **kwargs)

    monkeypatch.setattr(app_module.model_jobs, "run", spy)
    b = Building([0.0, 3.0])
    b.slab([(0, 0), (8, 0), (8, 6), (0, 6)], 0.0, b.storeys[0])
    path = b.write(tmp_path / "c.ifc")
    c = TestClient(app_module.app)
    with open(path, "rb") as fh:
        c.post("/api/import", files={"file": (path.name, fh)})
    c.post("/api/analyze")
    c.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []})
    assert c.post("/api/ifc/semantic").status_code == 200
    assert seen["calls"][0] == app_module.VIEW_MAX_ELEMENTS < app_module.SEMANTIC_MAX_ELEMENTS   # browser view guard
    assert seen["calls"][-1] == app_module.SEMANTIC_MAX_ELEMENTS


def test_guard_still_refuses_beyond_the_limit(tmp_path):
    from ifc_geometry_service import extract_ifc_geometry
    from tests.ifc_factory import Building
    b = Building([0.0, 3.0])
    for i in range(3):
        b.slab([(i * 5, 0), (i * 5 + 4, 0), (i * 5 + 4, 4), (i * 5, 4)], 0.0, b.storeys[0])
    with pytest.raises(ValueError, match="VBB_SEMANTIC_MAX_ELEMENTS"):
        extract_ifc_geometry(b.write(tmp_path / "g.ifc"), max_elements=2)


def test_view_limit_is_reported_in_plain_words(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    from state_store import ProjectStateStore
    from tests.ifc_factory import Building

    for name in ("UPLOAD_DIR", "SEMANTIC_DIR", "CACHE_DIR"):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(app_module, name, tmp_path / name)
    monkeypatch.setattr(app_module, "store", ProjectStateStore(tmp_path / "state.json"))
    monkeypatch.setattr(app_module, "VIEW_MAX_ELEMENTS", 1)
    b = Building([0.0, 3.0])
    for i in range(2):
        b.slab([(i * 5, 0), (i * 5 + 4, 0), (i * 5 + 4, 4), (i * 5, 4)], 0.0, b.storeys[0])
    path = b.write(tmp_path / "v.ifc")
    c = TestClient(app_module.app)
    with open(path, "rb") as fh:
        c.post("/api/import", files={"file": (path.name, fh)})
    c.post("/api/analyze")
    r = c.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": []})
    assert r.status_code == 413 and "เกินที่จอ 3D รับได้" in r.json()["detail"]
