"""The build shows where it is: stage, items done / total, Vissim used."""
from __future__ import annotations


def _feed(lines):
    from vissim_build_service import apply_progress_line
    state = {"stage": "validate", "done": 0, "total": 0, "totals": {}}
    for line in lines:
        apply_progress_line(state, line + "\n")
    return state


def test_stages_and_counts_follow_the_engine_output():
    head = ['Validation summary:',
            '{"levels": 7, "areas": 3, "semantic_obstacles": 4, "vissim_obstacles": 4, "vertical_connections": 2}',
            'Vissim COM ProgID: Vissim.Vissim.2026 (attempt 1/2)']
    s = _feed(head)
    assert s["stage"] == "connect" and s["prog_id"] == "Vissim.Vissim.2026"
    s = _feed(head + ["", "Creating Areas...", "  Area 1: Floor | Level=1", "  Area 2: Floor | Level=2"])
    assert (s["stage"], s["done"], s["total"]) == ("areas", 2, 3)
    s = _feed(head + ["Creating Obstacles...", "  IfcWall 1001: W | Level=1 | H=3.00 m"])
    assert (s["stage"], s["done"], s["total"]) == ("obstacles", 1, 4)
    s = _feed(head + ["Creating Vertical Connections...", "STAIRWAY 4001: Run 1 | 1 -> 2"])
    assert (s["stage"], s["done"], s["total"]) == ("vertical", 1, 2)
    s = _feed(head + ["VISSIM_FALLBACK: Vissim.Vissim.2026 did not start; trying Vissim.Vissim.2025",
                      "Vissim COM ProgID: Vissim.Vissim.2025 (attempt 2/2)", "Saving:", "Vissim model saved."])
    assert s["stage"] == "save" and s["fallback"] and s["prog_id"] == "Vissim.Vissim.2025"


def test_progress_api_reports_a_finished_build():
    from fastapi.testclient import TestClient

    import app as app_module
    from vissim_build_service import progress_finish, progress_start
    progress_start()
    progress_finish(False, "Vissim did not start")
    p = TestClient(app_module.app).get("/api/build/progress").json()
    assert p["running"] is False and p["result"] == "failed" and p["elapsed_sec"] >= 0
    assert [k for k, _ in p["stages"]][0] == "validate" and p["stages"][-1][0] == "save"
