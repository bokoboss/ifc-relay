"""Browser end-to-end checks (Playwright + Chromium). Run with VBB_E2E=1.

Covers the review's acceptance scenarios that need a real browser:
E2E-01 clean model -> Build enabled; a model with Viswalk checks still builds
(listed, one confirmation); plan passage -> regenerate -> zone reachable; exit mark -> re-prepared automatically -> measured from it.
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
    assert "สร้างไฟล์ได้" in page.text_content("#gateSummary")
    page.wait_for_function("document.getElementById('validateBtn').dataset.step === 'done'"
                           " && document.getElementById('buildViswalkBtn').dataset.step === 'next'")
    page.fill("#modelSearch", "IfcSlab")                            # search the loaded IFC objects
    page.wait_for_selector("#modelSearchResults button")
    page.click("#modelSearchResults button")
    page.wait_for_function("!document.getElementById('inspectorContent').classList.contains('hidden')")
    # UX-01: at 1366x768 the page itself does not scroll; the list is in the dock
    # and the viewer stays on screen with a usable height.
    assert page.evaluate("document.documentElement.scrollHeight <= innerHeight + 1")
    box = page.locator("#viewerCanvasHost").bounding_box()
    assert box["y"] >= 0 and box["y"] + box["height"] <= 768 and box["height"] >= 200
    assert page.get_attribute('.dock-tab[data-tab="issues"]', "aria-selected") == "true"
    assert page.is_enabled("#buildViswalkBtn")
    assert page.errors == []


def test_bim_tree_opens_storey_class_element(page, tmp_path):
    """Left panel tree: storey -> IFC class -> element; clicking shows it in the viewer."""
    b, _ = _two_storeys(with_stair=False)
    _open(page, b.write(tmp_path / "tree.ifc"))
    page.wait_for_selector("#modelTree .tree-storey")
    storeys = page.locator("#modelTree .tree-storey > summary .tree-label").all_text_contents()
    assert storeys[:2] == ["L1", "L2"]                              # IFC elevation order
    page.locator("#modelTree .tree-storey > summary").first.click()
    wall = page.locator("#modelTree .tree-type", has_text="IfcWall").first
    wall.locator("summary").click()
    page.wait_for_selector("#modelTree .tree-element")
    assert page.locator("#modelTree .tree-type:has-text('IfcWall') .tree-element").count() == 2
    assert page.locator("#modelTree .tree-element .tree-dot").first.get_attribute("class").split()[-1] \
        in ("include", "review", "exclude")
    page.locator("#modelTree .tree-element").first.click()
    page.wait_for_function("!document.getElementById('inspectorContent').classList.contains('hidden')")
    assert "ในโมเดลต้นฉบับ" in page.text_content("#messageText")
    assert page.errors == []


def test_pending_stairs_are_never_silent(page, tmp_path):
    """UX-01..04: stairs in review show next to "prepare", prepare asks, the bulk
    include runs from the dialog, and the model then has the stair."""
    b, _ = _two_storeys(with_stair=True)              # the stair stays "review" (no overrides)
    _open(page, b.write(tmp_path / "stairs.ifc"))
    page.wait_for_selector("#stairPendingChip:not(.hidden)", timeout=60000)
    assert "บันได 1 ชุดยังไม่ได้นำเข้า" in page.text_content("#stairPendingChip")
    page.click("#stairPendingChip")                    # takes the engineer to the stair block
    page.wait_for_selector("#stairReviewBlock.flash")
    page.click("#generateSemanticBtn")
    page.wait_for_selector("#stairPrepareConfirm[open]")
    assert "ยังไม่ได้นำเข้า 1 ชุด" in page.text_content("#stairPrepareLead")
    page.click("#stairPrepareInclude")
    page.wait_for_selector("#stairPendingChip.hidden", state="attached", timeout=60000)
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    assert page.text_content("#stairIncluded") == "1"
    sem = page.evaluate("currentSemantic")
    assert len(sem["vertical_connections"]) == 1
    assert sem["ifc_semantic"]["stair_decisions"]["review"] == 0
    assert page.errors == []


def test_viswalk_checks_listed_but_build_enabled(page, tmp_path):
    b, _ = _two_storeys(with_stair=False)          # closed room -> isolated zone: a Viswalk check, not a stop
    _open(page, b.write(tmp_path / "room.ifc"))
    _prepare_and_validate(page)
    assert page.locator("#gateList .gate-row.check", has_text="พื้นที่ที่เดินไปไม่ถึง").count() == 1
    # UX-03: the item opens to its places; "ดูตำแหน่ง" takes the viewer there
    row = page.locator("#gateList .gate-row.check", has_text="พื้นที่ที่เดินไปไม่ถึง")
    row.locator("summary").click()
    row.locator(".gate-locate").first.click()
    page.wait_for_function("window.IFCViewer.isPlan()")
    assert "วงสีส้ม" in page.text_content("#messageText")
    row.locator("summary").click()                                 # fold it again
    assert page.locator("#gateList input").count() == 0           # nothing to tick
    assert "ต้องตรวจ/แก้ใน Viswalk" in page.text_content("#gateSummary")
    assert page.is_enabled("#buildViswalkBtn")
    page.click("#buildViswalkBtn")                                 # one confirmation, in-app dialog
    page.wait_for_selector("#buildConfirm[open]")
    assert "พื้นที่ที่เดินไปไม่ถึง" in page.text_content("#buildConfirmList")
    page.click("#buildConfirmReview")                              # go back: no build, checks tab shown
    page.wait_for_selector("#buildConfirm", state="hidden")
    assert page.get_attribute('.dock-tab[data-tab="issues"]', "aria-selected") == "true"
    assert page.is_enabled("#buildViswalkBtn")
    assert page.errors == []


def _dock(page, tab):
    """Show a review-dock tab (lists live there, not on the page)."""
    if page.get_attribute(f'.dock-tab[data-tab="{tab}"]', "aria-selected") != "true" \
            or page.get_attribute("#reviewDock", "data-open") != "true":
        page.click(f'.dock-tab[data-tab="{tab}"]')


def _enter_plan(page, level="1"):
    # After preparing, the issue list may open (pending items); draw with it folded.
    if page.get_attribute("#reviewDock", "data-open") == "true":
        page.click("#dockToggle")
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
            const hit = document.elementFromPoint(p.x, p.y);
            const ok = a === JSON.stringify(p) && p.y >= Math.max(rc.top, 0) && p.y <= Math.min(rc.bottom, innerHeight)
              && p.x >= Math.max(rc.left, 0) && p.x <= Math.min(rc.right, innerWidth)
              && !!hit && hit.tagName === 'CANVAS';            // not under a toolbar
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
    _dock(page, "edits")
    page.wait_for_selector("#editsList .edit-row")
    import json as _json
    edits = _json.loads(urllib.request.urlopen(page.url.rstrip("/") + "/api/edits").read())["edits"]
    assert edits[0]["polygon"][0] == [0.0, 0.0]                # snapped to the floor corner
    assert len(edits[0]["polygon"]) == 4
    page.keyboard.press("Control+z")
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 0")
    page.keyboard.press("Control+y")
    page.wait_for_selector("#editsList .edit-row")

    # Delete from the list, undo (re-added under a new id), undo again: the older
    # "added" step must find the re-added edit.
    page.click("#editsList .edit-row button:has-text('ลบ')")
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 0")
    page.click("#planUndoBtn")
    page.wait_for_selector("#editsList .edit-row")
    page.click("#planUndoBtn")
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 0")
    page.click("#planRedoBtn")
    page.wait_for_selector("#editsList .edit-row")
    page.wait_for_function("!document.getElementById('planUndoBtn').disabled")

    # The history survives a reload.
    page.reload()
    page.wait_for_function("document.getElementById('editsList').children.length === 1", timeout=60000)
    page.wait_for_function("!document.getElementById('planUndoBtn').disabled")
    page.evaluate("document.getElementById('planUndoBtn').click()")
    page.wait_for_function("document.querySelectorAll('#editsList .edit-row').length === 0")
    assert not page.is_disabled("#planRedoBtn")
    assert page.errors == []


def test_plan_passage_reconnects_room(page, tmp_path):
    b, _ = _two_storeys(with_stair=False)
    _open(page, b.write(tmp_path / "plan.ifc"))
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    # UX-26: an unreachable floor is pending, so the issue list opens on it
    page.wait_for_function("document.getElementById('reviewDock').dataset.open === 'true'")
    assert page.get_attribute('.dock-tab[data-tab="issues"]', "aria-selected") == "true"
    assert "เรื่องให้ตัดสินใจหรือตรวจ" in page.text_content("#messageText")
    _enter_plan(page)
    page.click("#autoPrepareBtn[aria-pressed=true]")                     # step through by hand first
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
        _dock(page, "edits")
        page.wait_for_selector("#editsList .edit-row", timeout=15000)
        assert page.query_selector("#editsList .edit-review-pending")
    except Exception as exc:
        raise AssertionError(f"no edit saved: hits={hits} hint={page.text_content('#planHint')} "
                             f"plan={page.evaluate('window.IFCViewer.isPlan()')} {_diag(page)}") from exc
    assert page.is_disabled("#validateBtn")
    assert page.evaluate("window.IFCViewer.pendingPassageCuts()") >= 1     # UX-02: cut marked before the run
    # UX-05/09: the change is visible in the viewport and on the prepare button
    page.wait_for_selector("#staleBanner:not(.hidden)")
    assert page.get_attribute("#generateSemanticBtn", "data-step") == "stale"
    page.click("#generateSemanticBtn")
    page.wait_for_function("!document.getElementById('validateBtn').disabled", timeout=120000)
    page.wait_for_timeout(500)
    assert "ที่เดินไปไม่ถึง 1 แห่ง" in page.text_content("#connectivityNote")   # only the other floor (no stair)
    page.wait_for_selector("#staleBanner", state="hidden")
    page.wait_for_function("document.getElementById('generateSemanticBtn').dataset.step === 'done'")
    _dock(page, "edits")
    page.wait_for_selector("#editsList .edit-review-applied")          # F-19: the run used the passage
    assert "ใช้ครบ" in page.text_content("#editsReview")
    assert "วัดจากโครงข่ายใหญ่ที่สุด" in page.text_content("#connectivityNote")
    assert page.evaluate("window.IFCViewer.pendingPassageCuts()") == 0      # the model on screen is cut now

    # An exit mark changes no geometry; reachability is then measured from it.
    page.click(".plan-tool[data-tool=exit]")
    for x, y in ((4.0, 4.0), (6.0, 6.0)):
        pt = _plan_point(page, x, y)
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(300)
    page.wait_for_selector("#planConfirm:not(.hidden)", timeout=10000)
    assert "ทับพื้นที่เดิน" in page.text_content("#planConfirmText")
    page.click("#autoPrepareBtn[aria-pressed=false]")                    # UX-02: re-prepared without a click
    page.click("#planConfirmBtn")
    page.wait_for_function("document.getElementById('connectivityNote').textContent.includes('วัดจากจุดอ้างอิงทางออก 1 จุด')",
                           timeout=120000)
    page.wait_for_selector("#staleBanner", state="hidden")
    assert page.errors == []
