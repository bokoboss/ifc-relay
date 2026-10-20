"""F-07: one local project, but requests run on a thread pool. State changes
must not be lost, and a long job must not write back a stale copy."""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    import app as module
    from state_store import ProjectStateStore

    monkeypatch.setattr(module, "store", ProjectStateStore(tmp_path / "state.json"))
    return module


def _hammer(n_threads, per_thread, fn):
    start = threading.Barrier(n_threads)
    errors = []

    def run(t):
        start.wait()
        try:
            for k in range(per_thread):
                fn(t, k)
        except Exception as exc:          # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(t,)) for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors, errors


def test_concurrent_selection_changes_are_not_lost(app_module):
    from app import SelectionUpdate

    _hammer(6, 40, lambda t, k: app_module.update_selection(
        SelectionUpdate(global_id=f"G{t}_{k}", status="include")))
    overrides = app_module.store.read()["selection"]["overrides"]
    assert len(overrides) == 6 * 40


def test_concurrent_writes_never_share_a_temp_file(tmp_path):
    from state_store import ProjectStateStore

    store = ProjectStateStore(tmp_path / "s.json")
    _hammer(8, 50, lambda t, k: store.write({"t": t, "k": k}))   # used to race on one temp name
    assert set(store.read()) == {"t", "k"}
    assert not list(tmp_path.glob(".s.json.*.tmp"))


def test_long_job_result_is_not_written_over_a_changed_model(app_module, tmp_path):
    sem = tmp_path / "model.json"
    sem.write_text("{}", encoding="utf-8")
    app_module.store.write({"semantic": {"path": str(sem), "stale": False}, "build": {}})
    app_module.commit_build_status(sem, {"status": "validated"})
    assert app_module.store.read()["build"] == {"status": "validated"}

    # a selection change while the engine ran makes the model stale
    state = app_module.store.read()
    state["semantic"]["stale"] = True
    state["selection"] = {"overrides": {"G1": "exclude"}}
    app_module.store.write(state)
    with pytest.raises(HTTPException) as exc:
        app_module.commit_build_status(sem, {"status": "success"})
    assert exc.value.status_code == 409
    after = app_module.store.read()
    assert after["build"] == {"status": "validated"} and after["selection"]["overrides"] == {"G1": "exclude"}


def test_only_one_vissim_build_at_a_time(app_module, monkeypatch):
    assert app_module.BUILD_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as exc:
            app_module.build_current_semantic_in_vissim()
        assert exc.value.status_code == 409
    finally:
        app_module.BUILD_LOCK.release()
