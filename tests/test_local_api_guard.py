"""SEC-01: a web page from another site cannot change the project, and the
app answers only requests addressed to this computer (DNS rebinding)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_cross_site_and_foreign_host_are_refused(tmp_path):
    import app as app_module
    assert app_module.store.path == tmp_path / "project_state.json"
    app_module.store.write({"isolation_sentinel": True})
    c = TestClient(app_module.app)
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/project/reset", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/project/reset", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.get("/api/health", headers={"Host": "attacker.example:8765"}).status_code == 403
    assert app_module.store.read() == {"isolation_sentinel": True}
    assert c.post("/api/project/reset", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    assert c.post("/api/project/reset", headers={"Origin": "http://localhost:8765",
                                                 "Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert not app_module.store.path.exists()  # only the isolated file was reset


def test_ui_files_are_revalidated():
    from fastapi.testclient import TestClient

    import app as app_module

    c = TestClient(app_module.app)
    assert c.get("/static/app3d.js").headers.get("cache-control") == "no-cache"


def test_subprocess_app_state_uses_the_isolated_runtime():
    import os
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [sys.executable, "-c", "import app; app.store.write({'isolated': True}); "
         "app.store.reset(); print(app.store.path)"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True,
    )
    assert Path(result.stdout.strip()) == Path(os.environ["VBB_RUNTIME_DIR"]) / "project_state.json"
