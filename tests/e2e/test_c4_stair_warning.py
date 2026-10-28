"""C4: pending stair/ramp Units stay visible through the existing build dialog."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.e2e.test_browser_workflow import page, server, _dock, _open
from tests.test_stair_review import _model

pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1")
OUT = Path(__file__).resolve().parents[2] / "output" / "c4-local-20261028"


def _prepare_and_validate(page):
    # An enabled Validate button / visible Gate may still belong to the prior IFC.
    with page.expect_response(lambda res: res.request.method == 'POST'
                              and res.url.endswith('/api/ifc/semantic')) as prepared:
        page.click('#generateSemanticBtn')
    response = prepared.value
    assert response.status == 200, response.text()
    result = response.json()
    assert result['semantic_state'] == {'status': 'ready', 'stale': False}
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    with page.expect_response(lambda res: res.request.method == 'POST'
                              and res.url.endswith('/api/validate')) as validated:
        page.click('#validateBtn')
    assert validated.value.status == 200, validated.value.text()
    page.wait_for_selector('#gateSection:not(.hidden)', timeout=120000)
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)


def _pending(page):
    return page.locator('#gateList [data-item="stair_review_pending"]')


def _assert_pending(page, ids, count):
    row = _pending(page)
    assert row.locator('.gate-count').inner_text() == f"{count} ชุด"
    if not row.evaluate('(node) => node.open'):
        row.locator('summary').click()
    page.wait_for_function(
        "document.querySelector('[data-item=stair_review_pending] .gate-items') !== null")
    assert row.locator('.gate-items li').count() == count
    text = row.locator('.gate-items').inner_text()
    assert all(guid in text for guid in ids)


def _screenshot(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / name))


def test_c4_build_dialog_count_and_keyboard_link_to_units(page, server, tmp_path):
    path, ids = _model(tmp_path, with_ramp=True)
    _open(page, path)
    _prepare_and_validate(page)
    gate = page.request.get(server + '/api/gate').json()
    assert gate['passed'] and 'missing_vertical_connection' in gate['to_check']
    _assert_pending(page, [ids[k] for k in ('parent', 'loose', 'ramp')], 3)
    assert page.is_enabled('#buildViswalkBtn')
    builds = []
    page.on('request', lambda req: builds.append(req.url)
            if req.method == 'POST' and req.url.endswith('/api/build-vissim') else None)
    page.click('#buildViswalkBtn')
    page.wait_for_selector('#buildConfirm[open]')
    assert page.locator('dialog[open]').count() == 1
    assert '3 ชุด' in page.inner_text('#buildConfirmList')
    assert 'หลายชั้นแต่ไม่มีบันได/ทางลาด' in page.inner_text('#buildConfirmList')
    assert 'ยังต้องตรวจใน Viswalk' in page.inner_text('#buildConfirm')
    _screenshot(page, 'c4-build-confirm.png')
    link = page.get_by_role('button', name='บันได/ทางลาดที่ยังรอตรวจสอบ · ดูรายการ')
    link.focus()
    page.keyboard.press('Enter')
    page.wait_for_selector('#buildConfirm', state='hidden')
    page.wait_for_function(
        "document.activeElement === document.querySelector('[data-item=stair_review_pending] summary')")
    assert page.get_attribute('.dock-tab[data-tab="issues"]', 'aria-selected') == 'true'
    _assert_pending(page, [ids[k] for k in ('parent', 'loose', 'ramp')], 3)
    assert not builds  # navigation never submits the form or starts COM
    _screenshot(page, 'c4-pending-units.png')
    page.click('#buildViswalkBtn')
    page.wait_for_selector('#buildConfirm[open]')
    page.keyboard.press('Escape')
    page.wait_for_selector('#buildConfirm', state='hidden')
    assert page.is_enabled('#buildViswalkBtn')
    assert page.errors == []


def test_c4_selection_prepare_reload_and_revision_refresh_warnings(page, server, tmp_path):
    path, ids = _model(tmp_path, with_ramp=True)
    _open(page, path)
    _prepare_and_validate(page)
    page.fill('#modelSearch', ids['loose'])
    page.wait_for_selector('#modelSearchResults button')
    page.locator('#modelSearchResults button').click()
    page.click('.status-btn[data-status="include"]')
    page.wait_for_function("document.getElementById('buildViswalkBtn').disabled")
    assert page.request.get(server + '/api/gate').status == 400
    _prepare_and_validate(page)
    gate = page.request.get(server + '/api/gate').json()
    assert gate['passed'] and 'missing_vertical_connection' not in gate['to_check']
    _assert_pending(page, [ids['parent'], ids['ramp']], 2)
    assert ids['loose'] not in _pending(page).locator('.gate-items').inner_text()

    page.reload()
    page.wait_for_selector('#gateSection:not(.hidden)', timeout=120000)
    _dock(page, 'issues')
    _assert_pending(page, [ids['parent'], ids['ramp']], 2)
    assert page.locator('[data-item="missing_vertical_connection"]').count() == 0

    replacement, new_ids = _model(tmp_path, with_ramp=True)
    page.set_input_files('#fileInput', str(replacement))
    page.wait_for_selector('#importConfirm[open]', timeout=120000)
    page.click('#importConfirmGo')
    page.wait_for_selector('#importConfirm', state='hidden')
    # Closing the dialog precedes confirmation/audit/load; old buttons can still be enabled.
    page.wait_for_function("!document.getElementById('uploadBtn').disabled", timeout=120000)
    page.wait_for_function("!document.getElementById('generateSemanticBtn').disabled", timeout=120000)
    # Confirmed C3 import clears semantic output; selection changes above mark it stale instead.
    assert page.request.get(server + '/api/gate').status == 404
    overview = page.request.get(server + '/api/stairs').json()
    assert overview['counts']['review'] == 3
    assert {unit['global_id'] for unit in overview['units']} == {
        new_ids[k] for k in ('parent', 'loose', 'ramp')}
    assert page.is_disabled('#validateBtn')
    assert page.is_disabled('#buildViswalkBtn')
    assert page.locator('#gateSection').is_hidden()
    _prepare_and_validate(page)
    _assert_pending(page, [new_ids[k] for k in ('parent', 'loose', 'ramp')], 3)
    assert all(guid not in _pending(page).locator('.gate-items').inner_text() for guid in ids.values())
    assert page.locator('[data-item="missing_vertical_connection"]').count() == 1
    assert page.errors == []


def test_c4_pending_warning_is_visible_after_six_other_checks(page, server, tmp_path):
    path, _ = _model(tmp_path, with_ramp=True)
    _open(page, path)
    _prepare_and_validate(page)
    gate = page.request.get(server + '/api/gate').json()
    extras = [{"id": f"check-{n}", "title": f"Other check {n}", "policy": "check", "count": 1,
               "identities": [], "detail": "", "fingerprint": str(n)} for n in range(7)]
    gate['items'] = extras + gate['items']
    gate['to_check'] = [i['id'] for i in gate['items'] if i['policy'] == 'check']
    page.route('**/api/gate', lambda route: route.fulfill(json=gate))
    page.click('#buildViswalkBtn')
    page.wait_for_selector('#buildConfirm[open]')
    assert page.get_by_role('button', name='บันได/ทางลาดที่ยังรอตรวจสอบ · ดูรายการ').is_visible()
    assert '3 ชุด' in page.inner_text('#buildConfirmList')
    assert 'และอีก' in page.inner_text('#buildConfirmList')
    assert 'หลายชั้นแต่ไม่มีบันได/ทางลาด' in page.inner_text('#buildConfirmList')
    assert page.errors == []
