"""B2: history transactions across PATCH, DELETE, undo delete, undo update, redo.

The geometry PATCH is invoked through the frontend's B2 helper because manual
drag/resize UI is deliberately deferred to B3/B4. Delete and Undo/Redo are
exercised using actual browser controls and keyboard shortcuts.
"""
from __future__ import annotations

import os

import pytest

from tests.e2e.test_browser_workflow import _dock, _open, page, server
from tests.ifc_factory import Building

pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")


def _create_browser_edit(page, tmp_path):
    b = Building([0.0])
    b.slab([(0, 0), (12, 0), (12, 8), (0, 8)], 0.0, b.storeys[0])
    _open(page, b.write(tmp_path / "b2.ifc"))
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    # B2 tests transaction history, not canvas picking/drawing (U1/B3).
    # Create through the exact browser helper the drawing UI uses.
    page.click("#planModeBtn")
    page.wait_for_function("window.IFCViewer.isPlan()", timeout=20000)
    auto = page.locator("#autoPrepareBtn[aria-pressed=true]")
    if auto.count():
        auto.click()
    page.evaluate("""async () => saveEdit({
        tool: 'obstacle', level_key: 1,
        polygon: [[2,2], [4,2], [4,4], [2,4]],
    })""")
    _dock(page, "edits")
    page.wait_for_selector("#editsList .edit-row", timeout=20000)
    return page.request.get(page.url.rstrip("/") + "/api/edits").json()["edits"][0]


def _edits(page, server):
    return page.request.get(server + "/api/edits").json()["edits"]


def _update_via_frontend(page, edit, polygon):
    return page.evaluate(
        """async ({uid, polygon}) => {
            const edit = (await api('/api/edits')).edits.find(e => e.uid === uid);
            return updateEditGeometry(edit, polygon);
        }""",
        {"uid": edit["uid"], "polygon": polygon},
    )


def test_b2_update_delete_undo_delete_undo_update_redo_with_new_uid(page, server, tmp_path):
    first = _create_browser_edit(page, tmp_path)
    old_polygon = first["polygon"]
    shifted = [[2, 2], [5, 2], [5, 4], [2, 4]]

    changed = _update_via_frontend(page, first, shifted)
    assert changed["uid"] == first["uid"]
    assert changed["revision"] == 2
    assert len(_edits(page, server)) == 1

    page.locator("#editsList .edit-row button", has_text="ลบ").click()
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 0")
    assert _edits(page, server) == []

    page.click("#planUndoBtn")  # Undo Delete: POST, new UID, reset revision.
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 1")
    revived = _edits(page, server)[0]
    assert revived["uid"] != first["uid"]
    assert revived["revision"] == 1
    assert revived["polygon"] == shifted

    page.click("#planUndoBtn")  # Undo Update: PATCH the new UID/revision.
    page.wait_for_function("""async () => {
        const {edits} = await (await fetch('/api/edits')).json();
        return edits.length === 1 && edits[0].revision === 2
          && JSON.stringify(edits[0].polygon) === JSON.stringify([[2,2],[4,2],[4,4],[2,4]]);
    }""", timeout=20000)
    reverted = _edits(page, server)[0]
    assert reverted["uid"] == revived["uid"]
    assert reverted["revision"] == 2
    assert reverted["polygon"] == old_polygon

    # History restoration after reload must accept the new UID and update steps.
    page.reload()
    page.wait_for_function("!document.getElementById('planRedoBtn').disabled", timeout=60000)
    page.evaluate("document.getElementById('planRedoBtn').click()")
    page.wait_for_function("""async () => {
        const {edits} = await (await fetch('/api/edits')).json();
        return edits.length === 1 && edits[0].revision === 3;
    }""", timeout=20000)
    redone = _edits(page, server)[0]
    assert redone["uid"] == revived["uid"]
    assert redone["revision"] == 3
    assert redone["polygon"] == shifted
    assert not page.is_disabled("#planRedoBtn")  # Next redo is DELETE.

    page.click("#planRedoBtn")
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 0")
    assert _edits(page, server) == []
    assert page.errors == []


def test_b2_delete_conflict_reports_409_and_keeps_latest_edit(page, server, tmp_path):
    first = _create_browser_edit(page, tmp_path)
    polygon = [[2, 2], [6, 2], [6, 4], [2, 4]]
    response = page.request.patch(server + "/api/edits/" + first["id"], data={
        "expected_uid": first["uid"], "expected_revision": first["revision"],
        "polygon": polygon,
    })
    assert response.status == 200

    # The stale list still holds first.revision=1, so guarded DELETE must fail.
    page.locator("#editsList .edit-row button", has_text="ลบ").click()
    page.wait_for_function("document.getElementById('messageText').textContent.includes('409')")
    remaining = _edits(page, server)
    assert len(remaining) == 1
    assert remaining[0]["uid"] == first["uid"]
    assert remaining[0]["revision"] == 2
    assert remaining[0]["polygon"] == polygon
    assert page.errors == []


def test_b2_api_exposes_conflict_status_and_current_edit(page, server, tmp_path):
    first = _create_browser_edit(page, tmp_path)
    result = page.evaluate(
        """async ({id}) => {
            try {
                await api('/api/edits/' + id, {
                    method: 'PATCH',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        expected_uid: 'obsolete-uid', expected_revision: 1,
                        polygon: [[0,0],[2,0],[2,2],[0,2]]
                    }),
                });
                return {ok: true};
            } catch (err) {
                return {
                    ok: false, status: err.status, message: err.message,
                    currentUid: err.currentEdit?.uid, currentRevision: err.currentEdit?.revision,
                };
            }
        }""",
        {"id": first["id"]},
    )
    assert result["ok"] is False
    assert result["status"] == 409
    assert result["currentUid"] == first["uid"]
    assert result["currentRevision"] == 1
    assert result["message"] != "[object Object]"
    assert page.errors == []
