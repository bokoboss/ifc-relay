"""SEC-01: a web page from another site cannot change the project, and the
app answers only requests addressed to this computer (DNS rebinding)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_cross_site_and_foreign_host_are_refused():
    import app as app_module
    c = TestClient(app_module.app)
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/project/reset", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/project/reset", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.get("/api/health", headers={"Host": "attacker.example:8765"}).status_code == 403
    assert c.post("/api/project/reset", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    assert c.post("/api/project/reset", headers={"Origin": "http://localhost:8765",
                                                 "Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_ui_files_are_revalidated():
    from fastapi.testclient import TestClient

    import app as app_module

    c = TestClient(app_module.app)
    assert c.get("/static/app3d.js").headers.get("cache-control") == "no-cache"
