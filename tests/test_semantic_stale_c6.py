"""C6: semantic.stale is backend-authoritative, including a long-running
generation whose inputs change before its result is committed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from state_store import ProjectStateStore


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    import app as module

    source = tmp_path / "model.ifc"
    source.write_bytes(b"synthetic-ifc-placeholder")
    sem_dir = tmp_path / "semantic"
    sem_dir.mkdir()
    monkeypatch.setattr(module, "store", ProjectStateStore(tmp_path / "project.json"))
    monkeypatch.setattr(module, "SEMANTIC_DIR", sem_dir)
    monkeypatch.setattr(module, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(module, "prune_semantic_generations", lambda *a, **k: None)
    monkeypatch.setattr(module, "prune_geometry_cache", lambda *a, **k: None)
    state = {
        "schema_version": module.PROJECT_STATE_VERSION,
        "upload": {"path": str(source), "extension": ".ifc",
                   "original_name": source.name},
        "analysis": {"kind": "ifc", "status": "audited"},
        "geometry": {"status": "loaded"},
        "selection": {"mode": "auto", "overrides": {}},
        "manual_edits": [],
        "semantic": None,
        "build": {"status": "not_ready"},
    }
    module.store.write(state)
    return module, TestClient(module.app)


def _install_semantic_job(module, monkeypatch, *, mutate_inputs):
    """Use deterministic fake job output to test the commit race, not IFC geometry."""
    def complete_job(name, target, source, output_path, overrides, edits, **kwargs):
        assert name == "semantic"
        payload = {"ifc_semantic": {
            "summary": {"walkable_areas": 1}, "warnings": [],
            "manual_edits": [], "manual_edits_status": {},
        }, "levels": [], "areas": []}
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(payload), encoding="utf-8")
        if mutate_inputs:
            with module.store.lock:
                latest = module.store.read()
                latest["selection"]["overrides"]["changed_during_job"] = "exclude"
                latest["manual_edits"].append({"id": "E99", "kind": "obstacle",
                    "level_key": 1, "polygon": [[0,0],[1,0],[1,1],[0,1]]})
                module.store.write(latest)
        return None

    monkeypatch.setattr(module.model_jobs, "run", complete_job)


def test_c6_changed_inputs_during_generation_never_expose_export_or_validate(ctx, monkeypatch):
    module, client = ctx
    _install_semantic_job(module, monkeypatch, mutate_inputs=True)
    response = client.post("/api/ifc/semantic")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "stale"
    assert payload["stale"] is True
    assert payload["semantic_state"] == {"status": "ready", "stale": True}
    assert payload["download_url"] is None
    assert payload["engine_export_url"] is None

    state = client.get("/api/project").json()
    assert state["semantic"]["stale"] is True
    assert state["build"]["status"] == "selection_changed"
    assert state["selection"]["overrides"] == {"changed_during_job": "exclude"}

    readiness = client.get("/api/build-readiness").json()
    assert readiness["semantic_stale"] is True
    assert readiness["semantic_export_ready"] is False
    assert readiness["ifc_semantic_mapping_ready"] is False
    assert readiness["can_build_current_ifc"] is False

    assert client.get("/api/ifc/semantic").status_code == 409
    assert client.get("/api/ifc/semantic/download").status_code == 409
    assert client.get("/api/ifc/semantic/engine-download").status_code == 409
    assert client.post("/api/ifc/semantic/export-engine-input").status_code == 409
    assert client.post("/api/validate").status_code == 400
    draft = client.get("/api/ifc/semantic?draft=1")
    assert draft.status_code == 200 and draft.json()["stale"] is True


def test_c6_unchanged_generation_returns_ready_and_export_state(ctx, monkeypatch):
    module, client = ctx
    _install_semantic_job(module, monkeypatch, mutate_inputs=False)
    response = client.post("/api/ifc/semantic")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ok" and payload["stale"] is False
    assert payload["semantic_state"] == {"status": "ready", "stale": False}
    assert payload["download_url"] == "/api/ifc/semantic/download"
    assert payload["engine_export_url"] == "/api/ifc/semantic/export-engine-input"

    readiness = client.get("/api/build-readiness").json()
    assert readiness["semantic_stale"] is False
    assert readiness["semantic_export_ready"] is True
    assert readiness["ifc_semantic_mapping_ready"] is True
    assert client.get("/api/ifc/semantic").status_code == 200
    assert client.get("/api/ifc/semantic/download").status_code == 200


def test_c6_missing_semantic_file_never_reports_ready(ctx):
    module, client = ctx
    state = module.store.read()
    state["semantic"] = {
        "status": "ready", "stale": False, "path": "/tmp/does-not-exist-ifcrelay-semantic.json",
    }
    module.store.write(state)
    readiness = client.get("/api/build-readiness").json()
    assert readiness["semantic_export_ready"] is False
    assert readiness["ifc_semantic_mapping_ready"] is False
