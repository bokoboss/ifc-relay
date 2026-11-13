import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
import pytest

# Run geometry extraction inside the test process (no worker pool to outlive pytest).
os.environ.setdefault("VBB_GEOMETRY_IN_PROCESS", "1")
os.environ.setdefault("VBB_PERF_LOG", "")          # no performance log from tests


@pytest.fixture(scope="session", autouse=True)
def isolated_runtime(tmp_path_factory):
    # Subprocess app servers inherit this path too (including opt-in browser tests).
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("VBB_RUNTIME_DIR", str(tmp_path_factory.mktemp("runtime")))
        yield


@pytest.fixture(autouse=True)
def isolated_project_state(tmp_path, monkeypatch, isolated_runtime):
    # API tests must never fall back to the operator's live project state.
    import app as module
    from state_store import ProjectStateStore

    monkeypatch.setattr(module, "store", ProjectStateStore(tmp_path / "project_state.json"))
