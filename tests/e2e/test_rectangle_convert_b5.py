"""B5 — explicit Manual Rectangle resize and reversible polygon conversion.

Real Chromium E2E tests. IFC/generated objects remain read-only.
"""
from __future__ import annotations

import os

import pytest

from tests.e2e.test_browser_workflow import page, server, _dock, _plan_point
from tests.e2e.test_plan_ux_u1 import _ready, _add_manual
from tests.e2e.test_manual_drag_b3 import _edits, _wait_revision


pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")


def _turn_off_auto(page):
    if page.locator('#autoPrepareBtn[aria-pressed="true"]').count():
        page.click("#autoPrepareBtn")


def _select_rectangle(page, x=5, y=4):
    page.click('.plan-tool[data-tool="vertex"]')
    spot = _plan_point(page, x, y)
    page.mouse.click(spot["x"], spot["y"])
    page.wait_for_function(
        "() => window.IFCViewer.vertexEditingState().shapeType === 'rectangle'",
        timeout=10000,
    )


def _drag_vertex(page, sx, sy, ex, ey):
    start = _plan_point(page, sx, sy)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down(button="left")
    end = _plan_point(page, ex, ey)
    page.mouse.move(end["x"], end["y"], steps=8)
    page.mouse.up(button="left")


def _assert_poly_close(actual, expected, tolerance=1e-5):
    assert len(actual) == len(expected), (actual, expected)
    for a, b in zip(actual, expected):
        assert a == pytest.approx(b, abs=tolerance)


def test_b5_resize_rectangle_corner_keeps_opposite_and_undo_redo(page, server, tmp_path):
    _ready(page, tmp_path)
    _turn_off_auto(page)
    edit = _add_manual(page)
    patches = []
    page.on("request", lambda request: patches.append(request.url)
            if request.method == "PATCH" and "/api/edits/" in request.url else None)
    _select_rectangle(page)
    assert page.evaluate("window.IFCViewer.vertexEditingState().vertexCount") == 4
    _drag_vertex(page, 4, 3, 3, 2.5)
    _wait_revision(page, 2)
    resized = _edits(page, server)[0]
    assert resized["uid"] == edit["uid"]
    assert resized["shape_type"] == "rectangle"
    assert resized["level_key"] == edit["level_key"]
    _assert_poly_close(resized["polygon"], [[3, 2.5], [6, 2.5], [6, 5], [3, 5]])
    assert len(patches) == 1
    page.click("#planUndoBtn")
    _wait_revision(page, 3)
    _assert_poly_close(_edits(page, server)[0]["polygon"], edit["polygon"])
    page.click("#planRedoBtn")
    _wait_revision(page, 4)
    _assert_poly_close(_edits(page, server)[0]["polygon"], resized["polygon"])
    assert len(patches) == 3
    assert page.errors == []


def test_b5_rectangle_resize_cancel_has_no_patch(page, server, tmp_path):
    _ready(page, tmp_path)
    _turn_off_auto(page)
    edit = _add_manual(page)
    _select_rectangle(page)
    a = _plan_point(page, 4, 3)
    b = _plan_point(page, 3, 2.5)
    page.mouse.move(a["x"], a["y"])
    page.mouse.down(button="left")
    page.mouse.move(b["x"], b["y"], steps=7)
    assert page.evaluate("window.IFCViewer.planHasActiveDrag()")
    page.keyboard.press("Escape")
    page.mouse.up(button="left")
    assert _edits(page, server)[0]["revision"] == 1
    assert _edits(page, server)[0]["polygon"] == edit["polygon"]
    assert page.errors == []


def test_b5_rotated_rectangle_preserves_orthogonal_shape(page, server, tmp_path):
    _ready(page, tmp_path)
    _turn_off_auto(page)
    edit = page.evaluate("""async () => saveEdit({
      tool: 'obstacle', level_key: 1, shape_type: 'rectangle',
      polygon: [[5,1], [7,3], [5,5], [3,3]],
    })""")
    _select_rectangle(page, 5, 3)
    _drag_vertex(page, 5, 1, 5, 0)
    _wait_revision(page, 2)
    updated = _edits(page, server)[0]
    assert updated["uid"] == edit["uid"] and updated["shape_type"] == "rectangle"
    _assert_poly_close(updated["polygon"], [[5, 0], [7.5, 2.5], [5, 5], [2.5, 2.5]])
    assert page.errors == []


def test_b5_explicit_conversion_and_reversible_undo_redo(page, server, tmp_path):
    _ready(page, tmp_path)
    _turn_off_auto(page)
    edit = _add_manual(page)
    patches = []
    page.on("request", lambda request: patches.append(request.url)
            if request.method == "PATCH" and "/api/edits/" in request.url else None)
    _dock(page, "edits")
    assert page.locator(".edit-convert-btn").count() == 1
    assert _edits(page, server)[0]["revision"] == 1
    page.click(".edit-convert-btn")
    assert page.locator(".edit-confirm-convert").count() == 1
    assert _edits(page, server)[0]["revision"] == 1  # First click does not PATCH.
    assert patches == []
    page.click(".edit-confirm-convert")
    _wait_revision(page, 2)
    converted = _edits(page, server)[0]
    assert converted["shape_type"] == "polygon"
    assert converted["uid"] == edit["uid"]
    assert converted["polygon"] == edit["polygon"]
    page.wait_for_function(
        "() => document.querySelectorAll('#editsList .edit-convert-btn').length === 0",
        timeout=15000,
    )
    page.click("#planUndoBtn")
    _wait_revision(page, 3)
    restored = _edits(page, server)[0]
    assert restored["shape_type"] == "rectangle"
    assert restored["uid"] == edit["uid"]
    assert restored["polygon"] == edit["polygon"]
    page.click("#planRedoBtn")
    _wait_revision(page, 4)
    again = _edits(page, server)[0]
    assert again["shape_type"] == "polygon"
    assert again["uid"] == edit["uid"]
    assert len(patches) == 3  # Convert, Undo, Redo: one guarded PATCH each.
    assert page.errors == []


def test_b5_cancel_conversion_without_mutating_edit(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _add_manual(page)
    _dock(page, "edits")
    page.click(".edit-convert-btn")
    page.click(".edit-cancel-convert")
    assert page.locator(".edit-confirm-convert").count() == 0
    assert page.locator(".edit-convert-btn").is_enabled()
    current = _edits(page, server)[0]
    assert current["revision"] == 1
    assert current["shape_type"] == "rectangle"
    assert current["polygon"] == edit["polygon"]
    assert page.errors == []


def test_b5_conversion_conflict_does_not_overwrite_external_update(page, server, tmp_path):
    _ready(page, tmp_path)
    _turn_off_auto(page)
    edit = _add_manual(page)
    _dock(page, "edits")
    page.click(".edit-convert-btn")
    external = page.request.patch(
        server + "/api/edits/" + edit["id"],
        data={
            "expected_uid": edit["uid"], "expected_revision": 1,
            "polygon": [[4, 3], [7, 3], [7, 5], [4, 5]],
        },
    )
    assert external.status == 200, external.text()
    page.click(".edit-confirm-convert")
    page.wait_for_function(
        "() => document.getElementById('messageText').textContent.includes('(409)')",
        timeout=20000,
    )
    latest = _edits(page, server)[0]
    assert latest["revision"] == 2
    assert latest["shape_type"] == "rectangle"
    assert latest["polygon"] == [[4, 3], [7, 3], [7, 5], [4, 5]]
    assert page.errors == []
