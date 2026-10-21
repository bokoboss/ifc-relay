"""Visual regression: the main screens against reference images (Playwright + Chromium).

Run with VBB_E2E=1. Reference images live in tests/e2e/visual/. After an
intended change to the look, refresh them with

    VBB_E2E=1 VBB_UPDATE_VISUAL=1 python -m pytest -q tests/e2e/test_visual.py

and review the new PNGs in the diff. On a mismatch the actual image and a diff
image (changed pixels in magenta) are written to tests/e2e/visual-out/ (CI uploads
that folder as an artifact).

The 3D canvas is hidden: software WebGL output differs between machines and is
covered by the functional tests. Version text and transitions are neutralised so
only the interface itself is compared.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import numpy as np
import pytest

from tests.e2e.test_browser_workflow import (  # noqa: F401 - fixtures
    _dock, _open, _prepare_and_validate, page, server,
)
from tests.test_connectivity import _two_storeys

HERE = Path(__file__).resolve().parent
REF_DIR = HERE / "visual"
OUT_DIR = HERE / "visual-out"
UPDATE = os.environ.get("VBB_UPDATE_VISUAL") == "1"
pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1 to run browser tests")

# A pixel counts as changed when a channel differs by more than CHANNEL_TOL
# (absorbs anti-aliasing); the screen fails when more than MAX_CHANGED of its
# pixels changed (a moved panel or a new colour, not font hinting).
CHANNEL_TOL = 48
MAX_CHANGED = 0.004

STABLE_CSS = """
*, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }
#viewerCanvasHost canvas { visibility: hidden !important; }
#versionText, #appVersionText { visibility: hidden !important; }
"""


def _decode(png: bytes) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.int16)


def _settle(page) -> None:
    page.add_style_tag(content=STABLE_CSS)
    page.evaluate("document.fonts.ready")
    page.mouse.move(1, 1)                       # no hover state
    page.evaluate("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
    page.wait_for_timeout(250)


def _check(page, name: str) -> None:
    _settle(page)
    actual = page.screenshot(full_page=False)
    ref = REF_DIR / f"{name}.png"
    if UPDATE or not ref.exists():
        REF_DIR.mkdir(exist_ok=True)
        ref.write_bytes(actual)
        if not UPDATE:
            pytest.skip(f"reference {ref.name} created; commit it")
        return
    a, b = _decode(actual), _decode(ref.read_bytes())
    if a.shape != b.shape:
        _write_out(name, actual, None)
        pytest.fail(f"{name}: size {a.shape[1]}x{a.shape[0]} != reference {b.shape[1]}x{b.shape[0]}")
    changed = (np.abs(a - b).max(axis=2) > CHANNEL_TOL)
    ratio = float(changed.mean())
    if ratio > MAX_CHANGED:
        _write_out(name, actual, changed)
        pytest.fail(f"{name}: {ratio:.2%} of pixels changed (limit {MAX_CHANGED:.2%}); "
                    f"see tests/e2e/visual-out/{name}.actual.png and {name}.diff.png")


def _write_out(name: str, actual: bytes, changed) -> None:
    from PIL import Image
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{name}.actual.png").write_bytes(actual)
    if changed is not None:
        img = (_decode(actual) * 0.35 + 165).astype(np.uint8)       # faded screen
        img[changed] = (230, 0, 160)
        Image.fromarray(img).save(OUT_DIR / f"{name}.diff.png")


def _room_model(page, tmp_path):
    b, _ = _two_storeys(with_stair=False)      # closed room + unreached floor: a populated checklist
    _open(page, b.write(tmp_path / "visual.ifc"))
    _prepare_and_validate(page)


def test_visual_empty_workspace(page):
    page.wait_for_selector("#viewerEmpty")
    _check(page, "empty_1366")


def test_visual_issues_dock(page, tmp_path):
    _room_model(page, tmp_path)
    _dock(page, "issues")
    page.locator("#gateList .gate-row.check", has_text="พื้นที่ที่เดินไปไม่ถึง").locator("summary").click()
    _check(page, "issues_1366")


def test_visual_plan_with_legend(page, tmp_path):
    _room_model(page, tmp_path)
    page.click("#planModeBtn")
    page.select_option("#planLevelSelect", "1")
    page.wait_for_function("window.IFCViewer.isPlan()")
    page.click(".plan-tool[data-tool=passage]")
    page.click("#viewerLegend summary")
    _check(page, "plan_legend_1366")


def test_visual_build_confirm(page, tmp_path):
    _room_model(page, tmp_path)
    page.click("#buildViswalkBtn")
    page.wait_for_selector("#buildConfirm[open]")
    _check(page, "build_confirm_1366")


def test_visual_narrow_viewport(page, tmp_path):
    page.set_viewport_size({"width": 1024, "height": 700})
    _room_model(page, tmp_path)
    _dock(page, "issues")
    _check(page, "issues_1024")
