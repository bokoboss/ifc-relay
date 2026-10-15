from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def require(label: str, condition: bool) -> None:
    if condition:
        print(f"PASS: {label}")
    else:
        print(f"FAIL: {label}")
        raise SystemExit(1)


def main() -> None:
    print("Local Web App v0.3 Static QA")
    print("=" * 60)

    app = (ROOT / "app.py").read_text(encoding="utf-8")
    semantic = (ROOT / "ifc_semantic_service.py").read_text(encoding="utf-8")
    appjs = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    app3d = (ROOT / "static" / "app3d.js").read_text(encoding="utf-8")
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    setup = (ROOT / "setup_app.ps1").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    require("FastAPI reports version 0.3.0", 'version="0.3.0"' in app)
    require("Semantic generation endpoint exists", '@app.post("/api/ifc/semantic")' in app)
    require("Semantic download endpoint exists", '@app.get("/api/ifc/semantic/download")' in app)
    require("Engine-input export endpoint exists", 'export-engine-input' in app)
    require("Shapely dependency declared", "shapely" in requirements.lower())
    require("Semantic model emits physical walls", '"physical_segment": True' in semantic)
    require("Door relationships are read from IFC", "IfcRelFillsElement" in semantic and "IfcRelVoidsElement" in semantic)
    require("Windows are explicitly never pedestrian openings", '"windows_used_as_openings": 0' in semantic)
    require("Roof child slabs are filtered", "roof_children" in semantic)
    require("UI has Generate Semantic Model button", 'id="generateSemanticBtn"' in index)
    require("UI has semantic summary section", 'id="semanticSection"' in index)
    require("Browser calls semantic endpoint", "/api/ifc/semantic" in appjs)
    require("Viewer supports semantic preview", "loadSemantic(model)" in app3d)
    require("Viewer still dynamically loads local app3d", "app3d.js?v=030" in appjs)
    require("app3d imports local Three.js", "./vendor/three.module.js" in app3d)
    require("app3d imports local OrbitControls", "./vendor/jsm/controls/OrbitControls.js" in app3d)
    require("Setup downloads three.core.js", "three.core.js" in setup)

    # Catch accidental missing DOM IDs used by getElementById().
    ids_in_html = set(re.findall(r'id="([A-Za-z0-9_-]+)"', index))
    ids_in_js = set(re.findall(r"getElementById\(['\"]([A-Za-z0-9_-]+)['\"]\)", appjs))
    missing = sorted(ids_in_js - ids_in_html)
    require("All app.js DOM IDs exist in index.html", not missing)
    if missing:
        print("Missing IDs:", missing)

    print("=" * 60)
    print("STATIC QA RESULT: PASS")


if __name__ == "__main__":
    main()
