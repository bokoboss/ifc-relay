"""Non-visual UI contract checks for the BIM engineering workspace draft.

These checks intentionally avoid dependency on a browser or licensed Vissim.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
STUDIO = (ROOT / "static" / "app.css").read_text(encoding="utf-8")


class IdAndElementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.tags: dict[str, str] = {}
        self.classes: dict[str, list[str]] = {}
        self.anchors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        element_id = data.get("id")
        if element_id:
            self.ids.append(element_id)
            self.tags[element_id] = tag
            self.classes[element_id] = (data.get("class") or "").split()
        if tag == "link":
            self.anchors.append(data.get("href") or "")


def parsed() -> IdAndElementParser:
    obj = IdAndElementParser()
    obj.feed(HTML)
    obj.close()
    return obj


def test_dom_ids_unique_and_app_js_selectors_satisfied() -> None:
    dom = parsed()
    assert len(dom.ids) == len(set(dom.ids)), "Duplicate DOM ID after UI refactor"
    referenced = set(re.findall(r"getElementById\(['\"]([A-Za-z0-9_-]+)['\"]\)", JS))
    missing = sorted(referenced - set(dom.ids))
    assert not missing, "Missing JS contract IDs: " + ", ".join(missing)


def test_three_pane_workspace_and_stages_exist() -> None:
    dom = parsed()
    assert dom.tags["explorerSection"] == "section"
    assert "hidden" not in dom.classes["explorerSection"]
    assert dom.tags["viewerCanvasHost"] == "div"
    assert dom.tags["viewerEmpty"] == "div"
    assert dom.tags["storeyFilters"] == "div"
    assert dom.tags["categoryFilters"] == "div"
    assert dom.tags["inspectorContent"] == "div"
    for name in ("stepAnalyze", "stepExplore", "stepSelect", "stepPreview", "stepSemantic", "stepBuild"):
        assert name in dom.ids



def test_no_permanent_workflow_sidebar() -> None:
    """Legacy progress IDs remain for JS state but must not consume viewport width."""
    dom = parsed()
    assert '<aside class="sidebar">' not in HTML
    assert '<nav class="workflow"' not in HTML
    assert 'class="workflow-state hidden"' in HTML
    assert "topbar-brand" in HTML
    assert "environment-menu" in HTML
    assert dom.tags["healthText"] == "div"
    assert "command-index" not in HTML
    assert 'class="workspace-toolbar"' in HTML
    assert ".app-shell {display:flex;" in STUDIO          # no sidebar column
    assert ".workflow-state {display:none !important;}" in STUDIO


def test_primary_engineering_layout_preserved() -> None:
    dom = parsed()
    assert dom.tags["explorerSection"] == "section"
    assert "hidden" not in dom.classes["explorerSection"]
    assert dom.tags["viewerCanvasHost"] == "div"
    assert dom.tags["storeyFilters"] == "div"
    assert dom.tags["categoryFilters"] == "div"
    assert dom.tags["inspectorContent"] == "div"


def test_controls_and_exports_remain_wired() -> None:
    dom = parsed()
    for name in (
        "fileInput", "uploadBtn", "carrySelectionCheck", "analyzeBtn", "load3dBtn",
        "generateSemanticBtn", "validateBtn", "buildViswalkBtn",
        "downloadSemanticTopBtn", "downloadEngineTopBtn", "downloadInpxTopBtn",
        "geometryLoadMode", "geometryStoreySelect", "appendStoreyCheck",
        "resetBtn", "messageText",
    ):
        assert name in dom.ids
    assert 'id="downloadSemanticTopBtn" class="secondary-btn" disabled' in HTML
    assert 'id="downloadEngineTopBtn" class="secondary-btn" disabled' in HTML



def test_compact_toolbar_has_direct_primary_actions_and_secondary_tools() -> None:
    dom = parsed()
    for name in ("fileInput", "uploadBtn", "generateSemanticBtn", "validateBtn", "buildViswalkBtn"):
        assert name in dom.ids
    assert 'class="toolbar-primary"' in HTML
    assert 'class="toolbar-utilities"' in HTML
    assert 'class="tools-dropdown"' in HTML
    assert "เตรียมโมเดลคนเดิน" in HTML
    assert "สร้างไฟล์ Viswalk" in HTML
    assert "ซูมทั้งโมเดล" in HTML and "ซูมที่วัตถุ" in HTML
    assert "command-group" not in HTML
    assert "command-index" not in HTML
    assert "workspace-toolbar" in STUDIO
    assert "@media (max-width:1180px)" in STUDIO


def test_semantic_preparation_activates_simulation_preview_automatically() -> None:
    begin = JS.index("async function prepareModel(")
    end = JS.index("downloadSemanticTopBtn.addEventListener('click', () => {", begin)
    handler = JS[begin:end]
    assert "'/api/ifc/semantic'" in handler
    assert handler.index("v.loadSemantic(result.model)") < handler.index("v.setMode('simulation')")
    assert "if (previewMeshes > 0)" in handler
    assert "previewIssue" in handler
    assert "เตรียมโมเดลคนเดินเสร็จแล้ว" in handler


def test_studio_css_offline_and_responsive() -> None:
    dom = parsed()
    assert "/static/app.css?v=8" in dom.anchors                    # one stylesheet, fonts bundled
    assert (ROOT / "static" / "fonts" / "OFL.txt").exists()
    assert "@media (max-width:730px)" in STUDIO
    assert "@media (max-width:1060px)" in STUDIO
    assert "@import" not in STUDIO
    assert "https://" not in STUDIO
    assert ".viewer-host" in STUDIO
    assert ".explorer-layout" in STUDIO


def test_viewer_legend_matches_model_colours() -> None:
    """The legend swatches use the colours the viewer draws with."""
    view3d = (ROOT / "static" / "app3d.js").read_text(encoding="utf-8")
    for hex6 in ("77a7c8", "4f5962", "b18a57", "1f8a70", "d98e04", "c0392b", "2e9e5b", "34495e", "0e9fb6", "b86c4d"):
        assert f"--c:#{hex6}" in HTML and f"0x{hex6}" in view3d
    assert 'id="viewerLegend"' in HTML and "viewerLegend" in JS
