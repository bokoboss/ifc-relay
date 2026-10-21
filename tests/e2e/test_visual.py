"""Visual regression: the main screens against reference images (Playwright + Chromium).

Run with VBB_E2E=1. Reference images live in tests/e2e/visual/ and are taken
in CI by the "visual references" workflow (Actions tab, or a commit message
containing [visual-refs]), which commits them with the Chromium version in
BROWSER.txt. A run with another Chromium build skips the comparison but still
writes its screenshots to tests/e2e/visual-out/ for a look. Locally,

    VBB_E2E=1 VBB_UPDATE_VISUAL=1 python -m pytest -q tests/e2e/test_visual.py

rewrites the references with the local browser. On a mismatch the actual image and a diff
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

from tests.e2e.test_browser_workflow import (  # noqa: F401 - fixture
    _dock, _open, _prepare_and_validate, server,
)
from tests.test_connectivity import _two_storeys

HERE = Path(__file__).resolve().parent
REF_DIR = HERE / "visual"
OUT_DIR = HERE / "visual-out"
UPDATE = os.environ.get("VBB_UPDATE_VISUAL") == "1"
# CI sets this: a comparison that cannot run (no reference, other Chromium) fails
# instead of skipping, so a green CI run always means the screens were compared.
REQUIRED = os.environ.get("VBB_VISUAL_REQUIRED") == "1"
pytestmark = pytest.mark.skipif(os.environ.get("VBB_E2E") != "1", reason="set VBB_E2E=1 to run browser tests")

# Both images are averaged over POOL x POOL blocks first, so glyph hinting and
# anti-aliasing (which differ between Linux images) wash out while a moved
# panel, a new colour or changed text does not. A block counts as changed when a
# channel differs by more than CHANNEL_TOL; the screen fails when more than
# MAX_CHANGED of its blocks changed.
POOL = 4
CHANNEL_TOL = 24
MAX_CHANGED = 0.006

STABLE_CSS = """
*, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }
#viewerCanvasHost canvas { visibility: hidden !important; }
#versionText, #appVersionText { visibility: hidden !important; }
"""


@pytest.fixture()
def page(server):
    """Playwright's own headless Chromium (same build locally and in CI), 1366x768."""
    import urllib.request

    from playwright.sync_api import sync_playwright

    urllib.request.urlopen(urllib.request.Request(server + "/api/project/reset", method="POST"))
    args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
            "--font-render-hinting=none", "--disable-lcd-text", "--disable-font-subpixel-positioning"]
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=args)
        except Exception:  # noqa: BLE001 - this Playwright's browser is not installed here
            fallback = Path("/opt/pw-browsers/chromium")
            if not fallback.exists():
                raise
            browser = p.chromium.launch(executable_path=str(fallback), args=args)
        pg = browser.new_page(viewport={"width": 1366, "height": 768}, device_scale_factor=1)
        pg.browser_version = browser.version
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server + "/")
        pg.errors = errors
        yield pg
        browser.close()


def _pool(img: np.ndarray) -> np.ndarray:
    h, w = (img.shape[0] // POOL) * POOL, (img.shape[1] // POOL) * POOL
    return img[:h, :w].reshape(h // POOL, POOL, w // POOL, POOL, 3).mean(axis=(1, 3))


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
    stamp = REF_DIR / "BROWSER.txt"
    if UPDATE:
        REF_DIR.mkdir(exist_ok=True)
        ref.write_bytes(actual)
        stamp.write_text(f"Chromium {page.browser_version}\n", encoding="utf-8")
        return
    if not ref.exists():
        _write_out(name, actual, None)
        (pytest.fail if REQUIRED else pytest.skip)(f"no reference for {name}; run the 'visual references' workflow")
    taken_with = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else "?"
    if taken_with != f"Chromium {page.browser_version}":
        _write_out(name, actual, None)       # still useful to look at
        (pytest.fail if REQUIRED else pytest.skip)(
            f"references were taken with {taken_with}; this is Chromium {page.browser_version}")
    a, b = _decode(actual), _decode(ref.read_bytes())
    if a.shape != b.shape:
        _write_out(name, actual, None)
        pytest.fail(f"{name}: size {a.shape[1]}x{a.shape[0]} != reference {b.shape[1]}x{b.shape[0]}")
    changed = np.abs(_pool(a) - _pool(b)).max(axis=2) > CHANNEL_TOL
    ratio = float(changed.mean())
    if ratio > MAX_CHANGED:
        _write_out(name, actual, changed)
        pytest.fail(f"{name}: {ratio:.2%} of 4x4 blocks changed (limit {MAX_CHANGED:.2%}); "
                    f"see tests/e2e/visual-out/{name}.actual.png and {name}.diff.png")


def _write_out(name: str, actual: bytes, changed) -> None:
    from PIL import Image
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{name}.actual.png").write_bytes(actual)
    if changed is not None:
        img = (_decode(actual) * 0.35 + 165).astype(np.uint8)       # faded screen
        mask = np.kron(changed, np.ones((POOL, POOL), dtype=bool))
        img[:mask.shape[0], :mask.shape[1]][mask] = (230, 0, 160)
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
