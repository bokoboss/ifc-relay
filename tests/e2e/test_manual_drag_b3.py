"""B3 browser regressions: manual move is one guarded PATCH on pointer release.

Simulated IFC is synthetic. No source IFC, generated semantic, or Vissim COM
element is modified by the plan gesture.
"""
from __future__ import annotations

import os
import time

import pytest

from tests.e2e.test_browser_workflow import _plan_point, page, server
from tests.e2e.test_plan_ux_u1 import _add_manual, _ready

pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")


def _edits(page, server):
    return page.request.get(server + "/api/edits").json()["edits"]


def _drag(page, sx, sy, ex, ey):
    start = _plan_point(page, sx, sy)
    page.mouse.move(start["x"], start["y"])
    # Record the actual pointer-down target *after* moving the mouse, because
    # hovered UI can relayout/overlay the WebGL canvas.
    page.evaluate("""({x,y}) => {
      const el = document.elementFromPoint(x, y);
      if (window.__b3Debug) window.__b3Debug.startHit = {
        tag: el?.tagName, id: el?.id, className: String(el?.className || ''),
        point: {x, y},
        canvas: (() => {
          const r = document.querySelector('#viewerCanvasHost canvas').getBoundingClientRect();
          return {x:r.x,y:r.y,width:r.width,height:r.height};
        })(),
      };
    }""", {"x": start["x"], "y": start["y"]})
    page.mouse.down(button="left")
    # Selecting a manual shape reveals Inspector and may resize the canvas.
    # Resolve the destination in the *new* layout, after the down event.
    end = _plan_point(page, ex, ey)
    page.mouse.move(end["x"], end["y"], steps=8)
    page.mouse.up(button="left")


def _wait_revision(page, revision):
    """Poll an awaited HTTP response, not a truthy unresolved Promise.

    Browser E2E's wait_for_function cannot be relied on to resolve an async
    JS predicate: it may return before the fetch has completed. page.evaluate
    explicitly awaits the Promise for each observation.
    """
    deadline = time.monotonic() + 20
    observed = None
    while time.monotonic() < deadline:
        observed = page.evaluate("""async () => {
          const response = await fetch('/api/edits', {cache: 'no-store'});
          return (await response.json()).edits;
        }""")
        if len(observed or []) == 1 and observed[0]["revision"] == revision:
            return observed[0]
        page.wait_for_timeout(100)
    debug = page.evaluate("window.__b3Debug || null")
    raise AssertionError(
        f"Expected revision {revision}; latest server edits={observed}; "
        f"browser trace={debug}"
    )


def test_b3_manual_drag_one_patch_and_undo_redo(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _add_manual(page)
    before = [list(p) for p in edit["polygon"]]
    assert edit["revision"] == 1

    # Diagnostic: record the actual browser fetch payload, response, move
    # event, and pointer sequence together. Playwright's page.on(request) can
    # be delivered asynchronously, so absence there is not conclusive.
    pre_drag = _edits(page, server)[0]
    page.evaluate("""() => {
      const record = {fetches: [], moves: [], pointers: [], documentPointers: []};
      window.__b3Debug = record;
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (...args) => {
        const url = String(args[0]?.url || args[0]);
        const options = args[1] || {};
        const method = String(options.method || args[0]?.method || 'GET').toUpperCase();
        const entry = {url, method, body: options.body || null};
        if (url.includes('/api/edits') && method !== 'GET') {
          record.fetches.push(entry);
          try {
            const response = await originalFetch(...args);
            entry.status = response.status;
            entry.response = await response.clone().json().catch(() => null);
            return response;
          } catch (error) {
            entry.error = String(error);
            throw error;
          }
        }
        return originalFetch(...args);
      };
      window.addEventListener('manual-edit-move', e =>
        record.moves.push({uid: e.detail?.edit?.uid,
          oldPolygon: e.detail?.edit?.polygon, polygon: e.detail?.polygon}), true);
      document.addEventListener('pointerdown', e =>
        record.documentPointers.push({
          type: 'pointerdown',
          target: {tag: e.target?.tagName, id: e.target?.id,
            cls: String(e.target?.className || '').slice(0, 150)},
          x: e.clientX, y: e.clientY, button: e.button,
        }), true);
      const canvas = document.querySelector('#viewerCanvasHost canvas');
      for (const type of ['pointerdown', 'pointerup', 'pointercancel']) {
        canvas.addEventListener(type, e => record.pointers.push({
          type, button: e.button, pointerId: e.pointerId,
          x: e.clientX, y: e.clientY,
        }), true);
      }
    }""")
    patches = []
    # Record what the browser actually sent: a revision increment can occur
    # even when the requested drag ended up near its original coordinates.
    page.on("request", lambda request: patches.append({
        "url": request.url, "body": request.post_data,
    }) if request.method == "PATCH" and "/api/edits/" in request.url else None)
    _drag(page, 5, 4, 7, 5)
    _wait_revision(page, 2)
    moved = _edits(page, server)[0]
    assert moved["uid"] == edit["uid"]
    assert moved["level_key"] == edit["level_key"]
    assert moved["shape_type"] == edit["shape_type"]
    expected = [[x + 2, y + 1] for x, y in before]
    debug = page.evaluate("window.__b3Debug")
    assert moved["polygon"] == expected, (
        f"B3 trace: pre_drag={pre_drag}, after={moved}, expected={expected}, "
        f"playwright_requests={patches}, browser_trace={debug}"
    )
    assert len(patches) == 1  # no requests during pointermove
    page.wait_for_function(
        "() => document.getElementById('selectedMapping').textContent.includes('Revision 2')",
        timeout=10000,
    )

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


def test_b3_near_polygon_border_is_empty_space_pan_not_move(page, server, tmp_path):
    _ready(page, tmp_path)
    edit = _add_manual(page)
    # x=3.35 is 0.65 m outside the shape (left edge x=4). The historic
    # THREE.Line default 1m ray threshold used to accidentally arm a drag.
    start = _plan_point(page, 3.35, 4)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down(button="left")
    page.mouse.move(start["x"] - 70, start["y"], steps=7)
    page.mouse.up(button="left")
    stored = _edits(page, server)[0]
    assert stored["uid"] == edit["uid"]
    assert stored["revision"] == 1
    assert stored["polygon"] == edit["polygon"]
    assert page.errors == []
