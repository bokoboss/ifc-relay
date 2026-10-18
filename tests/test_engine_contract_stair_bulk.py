from __future__ import annotations

from tests.engine_contract import engine_validate, issue_types, requires_engine
from tests.test_stair_review import _model, _open, client  # noqa: F401  (fixture)


@requires_engine
def test_engine_accepts_bulk_included_stairs(client, tmp_path):  # noqa: F811
    path, _ = _model(tmp_path)
    _open(client, path)
    client.post("/api/stairs/bulk", json={"status": "include"})
    sem = client.post("/api/ifc/semantic").json()["model"]
    v = engine_validate(sem, tmp_path)
    assert v["build_allowed"] and v["summary"]["vertical_connections"] == 3
    assert "obstacle_overlap" not in issue_types(v)
