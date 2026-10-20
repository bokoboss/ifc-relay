"""Static contract for the 2D plan editor and overlay mode (browser behaviour is in QA)."""
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def test_plan_controls_exist_and_are_wired():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for element_id in ("overlayModeBtn", "planModeBtn", "planToolbar", "planLevelSelect", "editsList"):
        assert f'id="{element_id}"' in html
    for tool in ("select", "measure", "walkable", "obstacle", "passage"):
        assert f'data-tool="{tool}"' in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "window.addEventListener('plan-rect'" in app and "'/api/edits'" in app
    viewer = (STATIC / "app3d.js").read_text(encoding="utf-8")
    for api in ("enterPlan(levelKey)", "exitPlan()", "setPlanTool(tool)", "setManualEdits(edits)"):
        assert api in viewer
    assert "mode === 'overlay'" in viewer
