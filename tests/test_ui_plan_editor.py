"""Static contract for the 2D plan editor and overlay mode (browser behaviour is in QA)."""
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def test_plan_controls_exist_and_are_wired():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for element_id in ("overlayModeBtn", "planModeBtn", "planToolbar", "planLevelSelect", "editsList"):
        assert f'id="{element_id}"' in html
    for tool in ("select", "measure", "walkable", "obstacle", "passage"):
        assert f'data-tool="{tool}"' in html
    from tests.ui_sources import app_js
    app = app_js()
    assert "window.addEventListener('plan-shape'" in app and "'/api/edits'" in app
    for element_id in ('planConfirmBtn', 'planUndoBtn', 'planRedoBtn', 'planSizeInput'):
        assert f'id="{element_id}"' in html
    assert 'data-shape="poly"' in html
    viewer = (STATIC / "app3d.js").read_text(encoding="utf-8")
    for api in ("enterPlan(levelKey)", "exitPlan()", "setPlanTool(tool)", "setManualEdits(edits)"):
        assert api in viewer
    assert "mode === 'overlay'" in viewer
