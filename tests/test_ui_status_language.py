"""Status messages are Thai and the viewer badge follows the display mode."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

LEGACY_ENGLISH = [
    "Validation complete:",
    "Validation failed:",
    "Build failed:",
    "BUILD SUCCESS",
    "Building Viswalk model",
    "Import failed:",
    "Analysis failed:",
    "3D load failed:",
    "Generate Semantic Model",
    "loaded mesh elements",
]


def test_no_legacy_english_status_messages():
    found = [text for text in LEGACY_ENGLISH if text in APP_JS]
    assert not found, f"English status text left in app.js: {found}"


def test_set_message_literals_are_thai():
    literals = re.findall(r"setMessage\(\s*['`]([^'`]*)['`]", APP_JS)
    assert literals, "no setMessage literals found"
    thai = re.compile(r"[฀-๿]")
    english_only = [t for t in literals if not thai.search(t) and t.strip() and not t.startswith("${")]
    assert not english_only, f"setMessage without Thai text: {english_only}"


def test_validation_message_separates_geometry_check_from_viswalk_check():
    assert "Engine สร้างไฟล์ได้" in APP_JS and "ยังไม่ใช่การรับรองโมเดล" in APP_JS
    assert "ตรวจสอบโมเดล" not in INDEX                    # the button says "ตรวจ Geometry"


def test_viewer_badge_follows_mode():
    assert 'id="viewportIdentLabel"' in INDEX
    assert "IFC GEOMETRY" not in INDEX
    assert APP_JS.count("setViewerBadge('simulation')") >= 2  # mode button + after preparing the model
    assert APP_JS.count("setViewerBadge('source')") >= 2      # mode button + after (re)loading geometry
