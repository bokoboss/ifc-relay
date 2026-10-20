"""Browser end-to-end checks (Playwright + Chromium). Run with VBB_E2E=1.

Covers the review's acceptance scenarios that need a real browser:
E2E-01 clean model -> gate passed -> Build enabled; acknowledgement with a
required reason; plan passage -> regenerate -> zone reachable.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from tests.ifc_factory import Building
from tests.test_connectivity import _two_storeys

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1 to run browser tests")
LOADED = "/WebGL/.test(document.getElementById('viewerStatus')?.textContent||'')"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("project_root")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, VBB_PROJECT_ROOT=str(root))
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    yield base
    proc.terminate()
    proc.wait(timeout=20)


@pytest.fixture()
def page(server):
    from playwright.sync_api import sync_playwright

    urllib.request.urlopen(urllib.request.Request(server + "/api/project/reset", method="POST"))
    exe = "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
    args = (["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] if exe
            else ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe, args=args)
        pg = browser.new_page(viewport={"width": 1366, "height": 768})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server + "/")
        pg.errors = errors
        yield pg
        browser.close()


def _diag(page) -> str:
    js = ("JSON.stringify({viewer: document.getElementById('viewerStatus')?.textContent,"
          " message: document.querySelector('.message-panel')?.innerText,"
          " webgl: !!document.createElement('canvas').getContext('webgl2') || !!document.createElement('canvas').getContext('webgl'),"
          " diag: window.IFCViewerDiagnostics || null})")
    try:
        return page.evaluate(js) + f" errors={page.errors}"
    except Exception as exc:  # noqa: BLE001
        return f"diag failed: {exc}"


def _open(page, path: Path):
    page.set_input_files("#fileInput", str(path))
    try:
        page.wait_for_function(LOADED, timeout=120000)
    except Exception as exc:
        raise AssertionError(f"model did not open: {_diag(page)}") from exc


def _prepare_and_validate(page):
    page.click("#generateSemanticBtn")
    try:
        page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    except Exception as exc:
        raise AssertionError(f"pedestrian model not ready: {_diag(page)}") from exc
    page.click("#validateBtn")
    page.wait_for_selector("#gateSection:not(.hidden)", timeout=120000)
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)


def test_clean_model_enables_build_without_acknowledgement(page, tmp_path):
    """E2E-01."""
    b = Building([0.0, 3.4])
    b.slab([(0, 0), (12, 0), (12, 8), (0, 8)], 0.0, b.storeys[0])
    _open(page, b.write(tmp_path / "clean.ifc"))
    _prepare_and_validate(page)
    assert "ผ่านด่านตรวจแล้ว" in page.text_content("#gateSummary")
    assert page.is_enabled("#buildViswalkBtn")
    assert page.errors == []


def test_reason_required_then_build_enabled(page, tmp_path):
    b, _ = _two_storeys(with_stair=False)          # closed room -> isolated zone (reason required)
    _open(page, b.write(tmp_path / "room.ifc"))
    _prepare_and_validate(page)
    assert not page.is_enabled("#buildViswalkBtn")
    row = page.locator("#gateList .gate-row.ack", has_text="พื้นที่ที่เดินไปไม่ถึง")
    row.locator("input[type=checkbox]").click()                   # the server refuses: no reason
    page.wait_for_function("!document.querySelector('#gateList .gate-row.ack input').checked", timeout=10000)
    assert not page.is_enabled("#buildViswalkBtn")
    row.locator(".gate-reason").fill("ช่องท่อ")
    row.locator("input[type=checkbox]").check()
    page.wait_for_function("!document.getElementById('buildViswalkBtn').disabled", timeout=10000)
    assert page.errors == []


def _enter_plan(page, level="1"):
    page.click("#planModeBtn")
    page.select_option("#planLevelSelect", level)
    page.evaluate("document.getElementById('viewerCanvasHost').scrollIntoView({block: 'center'})")
    _plan_point(page, 0, 0)       # plan camera has settled (fit happens on the next frames)


def _plan_point(page, x, y):
    """Viewport point of plan coordinate (x, y), on the canvas and stable for two frames.

    Panels below the viewer fill in asynchronously and can scroll the page after
    _enter_plan; a stale point then lands off the canvas. page.evaluate awaits the
    promise (wait_for_function would treat the Promise object itself as truthy).
    """
    js = f"""() => {{
        document.getElementById('viewerCanvasHost').scrollIntoView({{block: 'center'}});
        const a = JSON.stringify(window.IFCViewer.planScreenPoint({x}, {y}));
        return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => {{
            const p = window.IFCViewer.planScreenPoint({x}, {y});
            const rc = document.getElementById('viewerCanvasHost').getBoundingClientRect();
            const ok = a === JSON.stringify(p) && p.y >= Math.max(rc.top, 0) && p.y <= Math.min(rc.bottom, innerHeight)
              && p.x >= Math.max(rc.left, 0) && p.x <= Math.min(rc.right, innerWidth);
            r({{ok, p, rect: [rc.left, rc.top, rc.right, rc.bottom], view: [innerWidth, innerHeight, scrollY]}});
        }})));
    }}"""
    for _ in range(40):
        res = page.evaluate(js)
        if res["ok"]:
            return res["p"]
        page.wait_for_timeout(250)
    raise AssertionError(f"plan point ({x}, {y}) never on the canvas: {res}")


def _click_plan(page, x, y):
    pt = _plan_point(page, x, y)
    page.mouse.move(pt["x"], pt["y"])
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_timeout(150)


def test_polygon_snap_undo_redo(page, tmp_path):
    """F-12: free polygon, vertex snapping, preview/confirm, undo/redo."""
    b, _ = _two_storeys(with_stair=False)
    _open(page, b.write(tmp_path / "poly.ifc"))
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    _enter_plan(page)
    page.click(".plan-tool[data-tool=obstacle]")
    page.click(".plan-shape[data-shape=poly]")
    for x, y in ((0.03, 0.02), (4, 0), (4, 3), (2, 4.5)):        # first click 3 cm off the floor corner
        _click_plan(page, x, y)
    page.keyboard.press("Enter")
    page.wait_for_selector("#planConfirm:not(.hidden)")
    assert "4 มุม" in page.text_content("#planConfirmText")
    page.click("#planConfirmBtn")
    page.wait_for_selector("#editsList .edit-row")
    import json as _json
    edits = _json.loads(urllib.request.urlopen(page.url.rstrip("/") + "/api/edits").read())["edits"]
    assert edits[0]["polygon"][0] == [0.0, 0.0]                # snapped to the floor corner
    assert len(edits[0]["polygon"]) == 4
    page.keyboard.press("Control+z")
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 0")
    page.keyboard.press("Control+y")
    page.wait_for_selector("#editsList .edit-row")
    assert page.errors == []


def test_plan_passage_reconnects_room(page, tmp_path):
    b, _ = _two_storeys(with_stair=False)
    _open(page, b.write(tmp_path / "plan.ifc"))
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    _enter_plan(page)
    page.click(".plan-tool[data-tool=passage]")
    hits = []
    for x, y in ((13.5, 7.5), (14.5, 8.5)):
        pt = _plan_point(page, x, y)
        hits.append(page.evaluate(f"(() => {{ const e = document.elementFromPoint({pt['x']}, {pt['y']}); "
                                  f"return [{pt['x']:.0f}, {pt['y']:.0f}, e ? e.tagName + '#' + e.id + '.' + e.className : null]; }})()"))
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(300)
    try:
        page.wait_for_selector("#planConfirm:not(.hidden)", timeout=10000)
        assert "ตัดผนัง 1 ชิ้น" in page.text_content("#planConfirmText")
        page.click("#planConfirmBtn")
        page.wait_for_selector("#editsList .edit-row", timeout=15000)
    except Exception as exc:
        raise AssertionError(f"no edit saved: hits={hits} hint={page.text_content('#planHint')} "
                             f"plan={page.evaluate('window.IFCViewer.isPlan()')} {_diag(page)}") from exc
    assert page.is_disabled("#validateBtn")
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    page.wait_for_timeout(500)
    assert "ที่เดินไปไม่ถึง 1 แห่ง" in page.text_content("#connectivityNote")   # only the other floor (no stair)
    assert page.errors == []
