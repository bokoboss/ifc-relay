"""U1 browser contracts: Manual > Generated > IFC picking and safe plan UX."""
from __future__ import annotations

import os

import pytest
from tests.e2e.test_browser_workflow import _dock, _open, _plan_point, page, server
from tests.ifc_factory import Building
from tests.test_connectivity import _two_storeys
from tests.e2e.test_browser_workflow import _enter_plan, _click_plan

pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")


def _ready(page, tmp_path):
    b = Building([0.0])
    b.slab([(0, 0), (12, 0), (12, 9), (0, 9)], 0.0, b.storeys[0])
    _open(page, b.write(tmp_path / "u1.ifc"))
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    page.click("#planModeBtn")
    page.wait_for_function("window.IFCViewer.isPlan()", timeout=15000)
    # Focus within the visible plan viewport, avoiding the bottom toolbar.
    page.evaluate("window.IFCViewer.focusPlanPoint(5, 4, 1.5, 8)")


def _add_manual(page):
    return page.evaluate("""async () => saveEdit({
        tool: 'obstacle', level_key: 1, shape_type: 'rectangle',
        polygon: [[4,3], [6,3], [6,5], [4,5]],
    })""")


def test_u1_manual_pick_precedes_generated_and_inspector_is_readonly(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _add_manual(page)
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 1")
    pt = _plan_point(page, 5, 4)
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_function(
        "() => document.getElementById('selectedType').textContent.includes('Manual')",
        timeout=20000,
    )
    assert edit["id"] in page.text_content("#selectedName")
    assert "Manual" in page.text_content("#selectedGuid")
    assert all(page.is_disabled(".status-btn") for _ in [0]) if False else         page.evaluate("Array.from(document.querySelectorAll('.status-btn')).every(x => x.disabled)")
    _dock(page, "edits")
    assert page.get_attribute("#editsList .edit-row", "data-uid") is None if False else         page.get_attribute("#editsList .edit-row", "data-uid") == edit["uid"]
    page.locator("#editsList .edit-row").click(position={"x": 10, "y": 10})
    page.wait_for_function(
        "() => document.querySelector('#editsList .edit-row').classList.contains('selected')",
        timeout=20000,
    )
    assert page.errors == []


def test_u1_escape_select_and_pending_cancel_on_tool_change(page, server, tmp_path):
    _ready(page, tmp_path)
    page.click(".plan-tool[data-tool=obstacle]")
    page.click(".plan-shape[data-shape=poly]")
    assert "หลายเหลี่ยม" in page.text_content("#planHint")
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('plan-shape', {
        detail: {tool:'obstacle', level_key:1, shape_type:'polygon',
                 polygon:[[2,2],[4,2],[3,4]]}
    }))""")
    page.wait_for_selector("#planConfirm:not(.hidden)")
    page.click(".plan-tool[data-tool=passage]")
    assert page.locator("#planConfirm").evaluate("(el) => el.classList.contains('hidden')")
    assert page.evaluate("pendingShape === null")
    page.keyboard.press("Escape")
    assert page.get_attribute(".plan-tool[data-tool=select]", "class") and         "active" in page.get_attribute(".plan-tool[data-tool=select]", "class")
    assert page.evaluate("planTool === 'select' && !window.IFCViewer.planHasFirstPoint()")
    assert "เลือก" in page.text_content("#planHint")
    assert page.request.get(server + "/api/edits").json()["edits"] == []


def test_u1_polygon_doubleclick_finishes_without_ghost_vertex(page, server, tmp_path):
    _ready(page, tmp_path)
    page.click(".plan-tool[data-tool=obstacle]")
    page.click(".plan-shape[data-shape=poly]")
    for x, y in ((3, 3), (5, 3)):
        pt = _plan_point(page, x, y)
        page.mouse.click(pt["x"], pt["y"])
    pt = _plan_point(page, 5, 5)
    page.mouse.dblclick(pt["x"], pt["y"], delay=80)
    page.wait_for_selector("#planConfirm:not(.hidden)", timeout=15000)
    assert "3 มุม" in page.text_content("#planConfirmText")
    page.click("#planConfirmBtn")
    page.wait_for_function(
        "() => document.querySelectorAll('#editsList .edit-row').length === 1",
        timeout=20000,
    )
    edit = page.request.get(server + "/api/edits").json()["edits"][0]
    assert edit["shape_type"] == "polygon"
    assert len(edit["polygon"]) == 3
    assert len({tuple(p) for p in edit["polygon"]}) == 3
    assert page.evaluate("!window.IFCViewer.planHasFirstPoint()")
    assert page.errors == []


def test_u1_four_distinct_polygon_clicks_preserve_every_vertex(page, tmp_path):
    b, _ = _two_storeys(with_stair=False)
    _open(page, b.write(tmp_path / "four_vertices.ifc"))
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    _enter_plan(page)
    page.click(".plan-tool[data-tool=obstacle]")
    page.click(".plan-shape[data-shape=poly]")
    expected = ((0.03,0.02), (4,0), (4,3), (2,4.5))
    for i, (x,y) in enumerate(expected, 1):
        _click_plan(page, x, y)
        state = page.evaluate("""() => ({
            points: window.IFCViewer.planDraftPoints(),
            pending: pendingShape ? {polygon:pendingShape.polygon} : null,
            tool: planTool,
            shape: planShapeKind,
            hint: document.getElementById('planHint').textContent,
        })""")
        assert len(state["points"]) == i and state["pending"] is None, (
            f"After click {i} at {(x,y)} expected {i} points: {state}"
        )
