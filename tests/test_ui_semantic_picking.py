"""Static contract for pedestrian-model picking (P0-03); behaviour is checked in browser QA."""
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def test_viewer_picks_what_is_on_screen():
    js = (STATIC / "app3d.js").read_text(encoding="utf-8")
    assert "if (semanticGroup.visible)" in js            # simulation mode picks semantic objects
    assert "if (!modelGroup.visible) return;" in js       # hidden source meshes are never picked
    assert "semantic-element-selected" in js
    assert "showSource(guid)" in js
    assert "semanticPassesFilters" in js                  # storey filter applies to the pedestrian model


def test_inspector_has_source_links_and_review_lists():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for element_id in ("semanticSourceList", "offLevelList", "openingCandidateList"):
        assert f'id="{element_id}"' in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "window.addEventListener('semantic-element-selected'" in app
    assert "markSemanticStale()" in app
