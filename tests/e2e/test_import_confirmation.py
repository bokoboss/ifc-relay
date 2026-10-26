"""C3 real-browser regression: pending IFC upload cannot replace an open project
until the engineer confirms, and manual geometry is never carried by default.
"""
from __future__ import annotations

import os

import pytest

from tests.e2e.test_browser_workflow import page, server, _open
from tests.ifc_factory import Building

pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")


def test_c3_browser_cancel_decline_and_pending_details(page, server, tmp_path):
    a = Building([0.0])
    a.slab([(0, 0), (10, 0), (10, 7), (0, 7)], 0.0, a.storeys[0])
    first = a.write(tmp_path / "source.ifc")
    _open(page, first)

    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    for x in (1, 4):
        result = page.request.post(server + "/api/edits", data={
            "kind": "obstacle", "level_key": 1,
            "polygon": [[x, 1], [x + 1, 1], [x + 1, 2], [x, 2]],
        })
        assert result.ok, result.text()
    assert len(page.request.get(server + "/api/edits").json()["edits"]) == 2

    b = Building([0.0])
    b.slab([(0, 0), (9, 0), (9, 6), (0, 6)], 0.0, b.storeys[0])
    second = b.write(tmp_path / "replacement.ifc")

    # Stage a completely different project. The modal must be explicit and
    # the old committed project must remain available during the decision.
    page.set_input_files("#fileInput", str(second))
    page.wait_for_selector("#importConfirm[open]", timeout=120000)
    assert "source.ifc" in page.text_content("#importConfirmFiles")
    assert "replacement.ifc" in page.text_content("#importConfirmFiles")
    assert "2 รายการ" in page.text_content("#importConfirmEdits")
    assert page.is_checked("#importConfirmCarry") is False
    assert page.is_disabled("#importConfirmCarry")  # different project GUID
    assert page.request.get(server + "/api/project").json()["upload"]["original_name"] == "source.ifc"

    page.click("#importConfirmCancel")
    page.wait_for_selector("#importConfirm", state="hidden")
    assert page.request.get(server + "/api/project").json()["upload"]["original_name"] == "source.ifc"
    assert len(page.request.get(server + "/api/edits").json()["edits"]) == 2

    uploads = []
    page.on("request", lambda request: uploads.append(request.url)
            if request.method == "POST" and request.url.endswith("/api/import") else None)
    page.set_input_files("#fileInput", str(second))
    page.wait_for_selector("#importConfirm[open]", timeout=120000)
    staged_count = len(uploads)
    assert staged_count == 1
    page.click("#importConfirmGo")
    page.wait_for_selector("#importConfirm", state="hidden")
    page.wait_for_function(
        "() => document.getElementById('fileMeta').textContent.includes('replacement.ifc')",
        timeout=120000,
    )
    page.wait_for_function(
        "() => !document.getElementById('load3dBtn').disabled",
        timeout=120000,
    )
    assert len(uploads) == staged_count  # confirm did not upload IFC again
    assert page.request.get(server + "/api/project").json()["upload"]["original_name"] == "replacement.ifc"
    assert page.request.get(server + "/api/edits").json()["edits"] == []
    assert page.errors == []


def test_c3_browser_explicit_manual_carry_requires_spatial_ack(page, server, tmp_path):
    b = Building([0.0])
    b.slab([(0, 0), (10, 0), (10, 7), (0, 7)], 0.0, b.storeys[0])
    first = b.write(tmp_path / "revision_A.ifc")
    _open(page, first)
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    result = page.request.post(server + "/api/edits", data={
        "kind": "walkable", "level_key": 1,
        "polygon": [[0, 0], [2, 0], [2, 2], [0, 2]],
    })
    assert result.ok, result.text()

    # Same IFC project and XY. In absence of MapConversion, it is explicitly
    # unverified, so the engineer must acknowledge the alignment risk.
    second = b.write(tmp_path / "revision_B.ifc")
    page.set_input_files("#fileInput", str(second))
    page.wait_for_selector("#importConfirm[open]", timeout=120000)
    assert "ยังตรวจยืนยันระบบพิกัดไม่ได้ครบ" in page.text_content("#importConfirmIdentity")
    page.check("#importConfirmCarry")
    assert page.is_disabled("#importConfirmGo")
    page.check("#importConfirmRisk")
    assert page.is_enabled("#importConfirmGo")
    page.click("#importConfirmGo")
    page.wait_for_selector("#importConfirm", state="hidden")
    page.wait_for_function(
        "() => document.getElementById('fileMeta').textContent.includes('revision_B.ifc')",
        timeout=120000,
    )
    assert len(page.request.get(server + "/api/edits").json()["edits"]) == 1
    assert page.errors == []
