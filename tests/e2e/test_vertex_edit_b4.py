"""B4 — browser regressions for explicit Manual Polygon vertex editing.

All changes are one revision-guarded PATCH per operation and use the existing
B2 history. Rectangle conversion is intentionally deferred to B5.
"""
from __future__ import annotations

import os
import pytest

from tests.e2e.test_browser_workflow import _plan_point, page, server
from tests.e2e.test_plan_ux_u1 import _ready, _add_manual
from tests.e2e.test_manual_drag_b3 import _wait_revision, _edits

pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")


def _polygon_edit(page):
    # Avoid Auto Prepare moving/refreshing the plan during a test gesture.
    if page.locator('#autoPrepareBtn[aria-pressed="true"]').count():
        page.click('#autoPrepareBtn')
    edit = page.evaluate("""async () => saveEdit({
      tool: 'obstacle', level_key: 1, shape_type: 'polygon',
      polygon: [[4,3], [6,3], [6,5], [4,5]],
    })""")
    assert edit["shape_type"] == "polygon"
    page.click('.plan-tool[data-tool="vertex"]')
    p = _plan_point(page, 5, 4)
    page.mouse.click(p["x"], p["y"])
    page.wait_for_function(
        "() => window.IFCViewer.vertexEditingState().uid !== null",
        timeout=10000,
    )
    assert page.evaluate("window.IFCViewer.vertexEditingState().vertexCount") == 4
    return edit


def _move_vertex(page, x0, y0, x1, y1):
    start = _plan_point(page, x0, y0)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down(button="left")
    end = _plan_point(page, x1, y1)
    page.mouse.move(end["x"], end["y"], steps=8)
    page.mouse.up(button="left")


def _near_polygon(actual, expected, tolerance=1e-5):
    assert len(actual) == len(expected), (actual, expected)
    assert all(
        abs(float(a) - float(b)) <= tolerance
        for point, target in zip(actual, expected)
        for a, b in zip(point, target)
    ), (actual, expected)


def test_b4_vertex_drag_guarded_patch_and_undo_redo(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _polygon_edit(page)
    patch_requests = []
    page.on("request", lambda request: patch_requests.append(request.url)
            if request.method == "PATCH" and "/api/edits/" in request.url else None)

    _move_vertex(page, 4, 3, 3, 2.5)
    _wait_revision(page, 2)
    latest = _edits(page, server)[0]
    _near_polygon(latest["polygon"], [[3, 2.5], [6, 3], [6, 5], [4, 5]])
    assert latest["uid"] == edit["uid"]
    assert latest["shape_type"] == "polygon"
    assert latest["level_key"] == edit["level_key"]
    assert len(patch_requests) == 1
    page.wait_for_function(
        "() => document.getElementById('selectedMapping').textContent.includes('Revision 2')",
        timeout=15000,
    )
    page.click("#planUndoBtn")
    _wait_revision(page, 3)
    assert _edits(page, server)[0]["polygon"] == edit["polygon"]
    page.click("#planRedoBtn")
    _wait_revision(page, 4)
    _near_polygon(_edits(page, server)[0]["polygon"], latest["polygon"])
    assert len(patch_requests) == 3
    assert page.errors == []


def test_b4_alt_click_edge_inserts_and_undo_restores(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _polygon_edit(page)
    middle = _plan_point(page, 5, 3)
    page.keyboard.down("Alt")
    page.mouse.click(middle["x"], middle["y"])
    page.keyboard.up("Alt")
    _wait_revision(page, 2)
    changed = _edits(page, server)[0]
    assert changed["uid"] == edit["uid"]
    assert changed["shape_type"] == "polygon"
    assert len(changed["polygon"]) == 5
    _near_polygon([changed["polygon"][1]], [[5, 3]])
    page.click("#planUndoBtn")
    _wait_revision(page, 3)
    assert _edits(page, server)[0]["polygon"] == edit["polygon"]
    assert page.errors == []


def test_b4_delete_vertex_keeps_min_three_and_is_reversible(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _polygon_edit(page)
    corner = _plan_point(page, 4, 3)
    page.mouse.click(corner["x"], corner["y"])
    assert page.evaluate("window.IFCViewer.vertexEditingState().selectedVertexIndex") == 0
    page.keyboard.press("Delete")
    _wait_revision(page, 2)
    changed = _edits(page, server)[0]
    assert len(changed["polygon"]) == 3
    assert changed["uid"] == edit["uid"]
    page.keyboard.press("Backspace")
    page.wait_for_function(
        "() => document.getElementById('messageText').textContent.includes('อย่างน้อย 3')",
        timeout=10000,
    )
    assert _edits(page, server)[0]["revision"] == 2
    page.click("#planUndoBtn")
    _wait_revision(page, 3)
    assert _edits(page, server)[0]["polygon"] == edit["polygon"]
    assert page.errors == []


def test_b4_rectangle_cannot_be_mutated_or_converted_implicitly(page, server, tmp_path):
    _ready(page, tmp_path)
    if page.locator('#autoPrepareBtn[aria-pressed="true"]').count():
        page.click('#autoPrepareBtn')
    edit = _add_manual(page)
    page.click('.plan-tool[data-tool="vertex"]')
    p = _plan_point(page, 5, 4)
    page.mouse.click(p["x"], p["y"])
    page.wait_for_function("() => document.getElementById('planHint').textContent.includes('B5')")
    v = _plan_point(page, 4, 3)
    page.mouse.move(v["x"], v["y"])
    page.mouse.down()
    page.mouse.move(v["x"] - 25, v["y"] - 20, steps=5)
    page.mouse.up()
    page.keyboard.press("Delete")
    current = _edits(page, server)[0]
    assert current["revision"] == 1
    assert current["shape_type"] == "rectangle"
    assert current["polygon"] == edit["polygon"]
    assert not page.evaluate("window.IFCViewer.vertexEditingState().pending")
    assert page.errors == []


def test_b4_invalid_self_intersection_rejected_without_history(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _polygon_edit(page)
    # Move lower-left through the opposite edge, creating a bow-tie.
    _move_vertex(page, 4, 3, 5, 6)
    page.wait_for_function(
        "() => document.getElementById('messageText').textContent.includes('(400)')",
        timeout=15000,
    )
    stored = _edits(page, server)[0]
    assert stored["revision"] == 1
    assert stored["polygon"] == edit["polygon"]
    assert not page.evaluate("window.IFCViewer.vertexEditingState().pending")
    # The original add transaction remains; rejected PATCH created no update.
    assert len(page.evaluate("editHistory.undo")) == 1
    assert page.errors == []


def test_b4_esc_cancels_vertex_preview_without_patch(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _polygon_edit(page)
    start = _plan_point(page, 4, 3)
    end = _plan_point(page, 3, 2.5)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down(button="left")
    page.mouse.move(end["x"], end["y"], steps=6)
    assert page.evaluate("window.IFCViewer.vertexEditingState().pending")
    page.keyboard.press("Escape")
    page.mouse.up(button="left")
    assert page.evaluate("window.IFCViewer.vertexEditingState().tool") == "select"
    assert _edits(page, server)[0]["revision"] == 1
    assert _edits(page, server)[0]["polygon"] == edit["polygon"]
    assert page.errors == []
