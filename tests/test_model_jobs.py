"""Large-IFC loading: memory-scheduled jobs, clear failures, content-keyed cache."""
from __future__ import annotations

import json
import threading
import time

import pytest

import model_jobs
from model_jobs import JobFailed


def test_jobs_wait_when_their_estimates_do_not_fit(monkeypatch):
    monkeypatch.setattr(model_jobs.SCHEDULER, "budget_mb", lambda: 1000)
    active, peak = [0], [0]

    def job(est):
        with model_jobs.SCHEDULER.slot(est):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.15)
            active[0] -= 1

    for est, expected in ((700, 1), (300, 2)):          # 2 x 700 > 1000: one at a time; 2 x 300 fits
        peak[0] = 0
        threads = [threading.Thread(target=job, args=(est,)) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert peak[0] == expected


def test_a_job_larger_than_the_budget_still_runs_alone(monkeypatch):
    monkeypatch.setattr(model_jobs.SCHEDULER, "budget_mb", lambda: 100)
    with model_jobs.SCHEDULER.slot(5000) as info:
        assert info["parallel"] == 0


def test_fresh_process_job_and_log(tmp_path, monkeypatch):
    monkeypatch.delenv("VBB_GEOMETRY_IN_PROCESS", raising=False)
    monkeypatch.setattr(model_jobs, "LOG_PATH", tmp_path / "perf.jsonl")
    f = tmp_path / "x.ifc"
    f.write_bytes(b"0" * 1024)
    assert model_jobs.run("probe", "math:sqrt", 16.0, files=[f]) == 4.0
    entry = json.loads((tmp_path / "perf.jsonl").read_text().splitlines()[-1])
    assert entry["job"] == "probe" and entry["outcome"] == "ok" and entry["files"] == ["x.ifc"]
    assert entry["peak_mb"] is None or entry["peak_mb"] > 0


def test_a_worker_that_dies_is_reported_in_plain_words(tmp_path, monkeypatch):
    monkeypatch.delenv("VBB_GEOMETRY_IN_PROCESS", raising=False)
    monkeypatch.setattr(model_jobs, "LOG_PATH", tmp_path / "perf.jsonl")
    f = tmp_path / "x.ifc"
    f.write_bytes(b"0")
    with pytest.raises(JobFailed, match="หน่วยความจำไม่พอ"):
        model_jobs.run("crash", "os:_exit", 3, files=[f])       # the worker process vanishes
    assert json.loads((tmp_path / "perf.jsonl").read_text().splitlines()[-1])["outcome"] == "failed"


def test_iterator_that_cannot_start_is_an_error_not_an_empty_model(tmp_path, monkeypatch):
    import ifcopenshell.geom

    from ifc_geometry_service import GeometryFailed, extract_ifc_geometry
    from tests.ifc_factory import Building

    b = Building([0.0, 3.0])
    b.slab([(0, 0), (5, 0), (5, 5), (0, 5)], 0.0, b.storeys[0])
    path = b.write(tmp_path / "g.ifc")

    class Dead:
        def __init__(self, *a, **k):
            pass

        def initialize(self):
            return False

    monkeypatch.setattr(ifcopenshell.geom, "iterator", Dead)
    with pytest.raises(GeometryFailed, match="did not initialise"):
        extract_ifc_geometry(path)


def test_reimported_file_reuses_cached_geometry(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    from state_store import ProjectStateStore
    from tests.ifc_factory import Building

    for name in ("UPLOAD_DIR", "SEMANTIC_DIR", "CACHE_DIR"):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(app_module, name, tmp_path / name)
    monkeypatch.setattr(app_module, "store", ProjectStateStore(tmp_path / "state.json"))
    b = Building([0.0, 3.0])
    b.slab([(0, 0), (8, 0), (8, 6), (0, 6)], 0.0, b.storeys[0])
    path = b.write(tmp_path / "c.ifc")
    c = TestClient(app_module.app)
    sources = []
    for _ in range(2):
        with open(path, "rb") as fh:
            c.post("/api/import", files={"file": (path.name, fh)})
        assert len(c.get("/api/project").json()["upload"]["sha256"]) == 64
        c.post("/api/analyze")
        r = c.post("/api/ifc/geometry", json={"mode": "simulation_relevant", "storey_ids": [], "tier": "core"})
        assert r.status_code == 200
        geo = r.json()
        assert geo["outcome"] == "success" and geo["element_count"] == 1
        sources.append(geo["source_file"])
    assert sources[0] == sources[1]                     # second import served from the first one's cache
    cached = sorted(p.name for p in (tmp_path / "CACHE_DIR").glob("geo_*.json"))
    assert len(cached) == 2 and cached[1].endswith("_view2000.json")    # full meshes + lighter view copy
    assert c.post("/api/ifc/semantic").status_code == 200


def test_elements_that_could_not_be_meshed_reach_the_checklist(tmp_path):
    from gate_service import evaluate_gate
    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model
    from tests.ifc_factory import Building

    b = Building([0.0, 3.0])
    slab = b.slab([(0, 0), (5, 0), (5, 5), (0, 5)], 0.0, b.storeys[0])
    path = b.write(tmp_path / "m.ifc")
    geo = extract_ifc_geometry(path)
    geo["mesh_failures"] = [{"shape_id": int(slab.id()), "error": "RuntimeError: test"}]
    sem = build_semantic_model(path, geo, {})
    assert any("could not be tessellated" in w for w in sem["ifc_semantic"]["warnings"])
    item = next(i for i in evaluate_gate(sem, None)["items"] if i["id"] == "mesh_failed")
    assert item["policy"] == "check" and slab.GlobalId in item["identities"]


def test_view_copy_simplifies_only_heavy_meshes():
    from ifc_geometry_service import view_payload

    heavy_v, heavy_i = [], []
    for k in range(400):                               # a finely tessellated 1 x 0.1 x 2 m door
        x = k / 400
        heavy_v += [x, 0, 0, x, 0.1, 0, x, 0, 2.0]
        heavy_i += [3 * k, 3 * k + 1, 3 * k + 2] * 6
    light = {"global_id": "W", "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0], "indices": [0, 1, 2]}
    door = {"global_id": "D", "vertices": heavy_v, "indices": heavy_i}
    out = view_payload({"elements": [light, door], "triangle_count": 2401}, max_triangles=2000)
    w, d = out["elements"]
    assert w == light                                    # untouched
    assert d["simplified_from_triangles"] == 2400 and len(d["indices"]) // 3 < 20
    zs = d["vertices"][2::3]
    xs = d["vertices"][0::3]
    assert min(zs) == 0 and max(zs) == 2.0 and min(xs) == 0 and max(xs) >= 0.99
    assert out["simplified_elements"] == 1 and out["source_triangle_count"] == 2401
