"""State readers must not keep a Windows file handle open across replacement."""
from __future__ import annotations

import traceback

import pytest

from state_store import ProjectStateStore
from tests.test_state_concurrency import _hammer


@pytest.mark.parametrize("writers,readers", [(2, 4), (8, 0)])
def test_concurrent_reads_and_atomic_replacements(tmp_path, writers, readers):
    store = ProjectStateStore(tmp_path / "project_state.json")
    store.write({"revision": "initial", "payload": "initial" * 1024})

    def access(thread, step):
        try:
            if thread < writers:
                revision = f"{thread}:{step}"
                # Same transaction boundary as semantic commit and selection updates.
                with store.lock:
                    store.write({"revision": revision, "payload": revision * 1024})
            else:
                state = store.read()
                assert state["payload"] == state["revision"] * 1024
        except Exception:
            raise AssertionError(traceback.format_exc())

    _hammer(writers + readers, 100, access)
    assert not list(tmp_path.glob(".project_state.json.*.tmp"))


@pytest.mark.parametrize("winerror", [5, 32])
def test_transient_windows_replace_failure_retries_same_complete_file(tmp_path, monkeypatch, winerror):
    import state_store as module

    store = ProjectStateStore(tmp_path / "project_state.json")
    store.write({"revision": "old"})
    replace = module.os.replace
    calls = []
    waits = []

    def busy_once(source, destination):
        calls.append(source)
        if len(calls) == 1:
            assert store.read() == {"revision": "old"}
            error = PermissionError("temporary Windows handle")
            error.winerror = winerror
            raise error
        replace(source, destination)

    monkeypatch.setattr(module.os, "replace", busy_once)
    monkeypatch.setattr(module.time, "sleep", waits.append)
    store.write({"revision": "new"})
    assert store.read() == {"revision": "new"}
    assert len(calls) == 2 and calls[0] == calls[1]
    assert waits == [0.01]
    assert not list(tmp_path.glob(".project_state.json.*.tmp"))


@pytest.mark.parametrize("winerror,attempts", [(5, 3), (32, 3), (None, 1)])
def test_permanent_replace_failure_preserves_old_state_and_propagates(tmp_path, monkeypatch,
                                                                    winerror, attempts):
    import state_store as module

    store = ProjectStateStore(tmp_path / "project_state.json")
    store.write({"revision": "old"})
    calls = []
    waits = []
    error = PermissionError("persistent denial")
    if winerror is not None:
        error.winerror = winerror

    def denied(source, destination):
        calls.append(source)
        raise error

    monkeypatch.setattr(module.os, "replace", denied)
    monkeypatch.setattr(module.time, "sleep", waits.append)
    with pytest.raises(PermissionError) as caught:
        store.write({"revision": "new"})
    assert caught.value is error
    assert store.read() == {"revision": "old"}
    assert len(calls) == attempts
    assert waits == ([0.01, 0.02] if attempts == 3 else [])
