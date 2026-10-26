"""B3 browser regressions: manual move is one guarded PATCH on pointer release.

Simulated IFC is synthetic. No source IFC, generated semantic, or Vissim COM
element is modified by the plan gesture.
"""
from __future__ import annotations

import os

import pytest

from tests.e2e.test_browser_workflow import _plan_point, page, server
from tests.e2e.test_plan_ux_u1 import _add_manual, _ready

pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")


def _edits(page, server):
    return page.request.get(server + "/api/edits").json()["edits"]


def _drag(page, sx, sy, ex, ey):
    start = _plan_point(page, sx, sy)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down(button="left")
    # Selecting a manual shape reveals Inspector and may resize the canvas.
    # Resolve the destination in the *new* layout, after the down event.
    end = _plan_point(page, ex, ey)
    page.mouse.move(end["x"], end["y"], steps=8)
    page.mouse.up(button="left")


def _wait_revision(page, revision):
    page.wait_for_function(
        """async r => {
          const result = await (await fetch('/api/edits')).json();
          return result.edits?.length === 1 && result.edits[0].revision === r;
        }""",
        arg=revision, timeout=20000,
    )


def test_b3_manual_drag_one_patch_and_undo_redo(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _add_manual(page)
    before = [list(p) for p in edit["polygon"]]
    assert edit["revision"] == 1

    patches = []
    page.on("request", lambda request: patches.append(request.url)
            if request.method == "PATCH" and "/api/edits/" in request.url else None)
    _drag(page, 5, 4, 7, 5)
    _wait_revision(page, 2)
    moved = _edits(page, server)[0]
    assert moved["uid"] == edit["uid"]
    assert moved["level_key"] == edit["level_key"]
    assert moved["shape_type"] == edit["shape_type"]
    assert moved["polygon"] == [[x + 2, y + 1] for x, y in before]
    assert len(patches) == 1  # no requests during pointermove

    page.click("#planUndoBtn")
    _wait_revision(page, 3)
    assert _edits(page, server)[0]["polygon"] == before
    page.click("#planRedoBtn")
    _wait_revision(page, 4)
    assert _edits(page, server)[0]["polygon"] == moved["polygon"]
    assert len(patches) == 3  # one PATCH each for move, undo, redo
    assert page.errors == []


def test_b3_click_and_escape_cancel_never_write(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _add_manual(page)
    start = _plan_point(page, 5, 4)
    page.mouse.click(start["x"], start["y"])
    assert _edits(page, server)[0]["revision"] == 1

    end = _plan_point(page, 6, 4)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down(button="left")
    page.mouse.move(end["x"], end["y"], steps=5)
    assert page.evaluate("!!document.querySelector('#viewerCanvasHost canvas.manual-dragging')")
    page.keyboard.press("Escape")
    page.mouse.up(button="left")
    page.wait_for_function(
        "() => !document.querySelector('#viewerCanvasHost canvas.manual-dragging')",
        timeout=10000,
    )
    actual = _edits(page, server)[0]
    assert actual["uid"] == edit["uid"]
    assert actual["revision"] == 1
    assert actual["polygon"] == edit["polygon"]
    assert page.errors == []


def test_b3_concurrent_external_patch_rolls_back_preview_and_reports_409(
    page, server, tmp_path
):
    _ready(page, tmp_path)
    edit = _add_manual(page)
    start = _plan_point(page, 5, 4)
    end = _plan_point(page, 7, 5)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down(button="left")
    page.mouse.move(end["x"], end["y"], steps=8)
    assert page.evaluate("!!document.querySelector('#viewerCanvasHost canvas.manual-dragging')")

    different = [[2, 3], [4, 3], [4, 5], [2, 5]]
    patch = page.request.patch(server + "/api/edits/" + edit["id"], data={
        "expected_uid": edit["uid"], "expected_revision": 1,
        "polygon": different,
    })
    assert patch.status == 200, patch.text()
    page.mouse.up(button="left")
    page.wait_for_function(
        "() => document.getElementById('messageText').textContent.includes('(409)')",
        timeout=20000,
    )
    stored = _edits(page, server)[0]
    assert stored["revision"] == 2
    assert stored["polygon"] == different
    assert page.evaluate("!document.querySelector('#viewerCanvasHost canvas.manual-dragging')")
    assert page.is_disabled("#planUndoBtn")
    assert page.is_disabled("#planRedoBtn")
    assert page.errors == []


def test_b3_generated_area_not_draggable(page, server, tmp_path):
    _ready(page, tmp_path)
    # No manual shapes: a drag in Select mode pans; it must never POST/PATCH.
    before = page.evaluate("window.IFCViewer.planScreenPoint(2, 2)")
    start = _plan_point(page, 2, 2)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down(button="left")
    page.mouse.move(start["x"] + 70, start["y"] + 20, steps=6)
    page.mouse.up(button="left")
    assert _edits(page, server) == []
    after = page.evaluate("window.IFCViewer.planScreenPoint(2, 2)")
    assert abs(after["x"] - before["x"]) > 10 or abs(after["y"] - before["y"]) > 10
    assert page.errors == []
