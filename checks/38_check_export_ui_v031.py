import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # repo root
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
appjs = "\n".join((ROOT / "static" / n).read_text(encoding="utf-8") for n in ("app.js", "app-plan.js", "app-model.js", "app-review.js", "app-tree.js", "app-build.js"))
app = (ROOT / "app.py").read_text(encoding="utf-8")

checks = [
    ("Top Download Semantic JSON button exists", 'id="downloadSemanticTopBtn"' in index),
    ("Top Download Engine JSON button exists", 'id="downloadEngineTopBtn"' in index),
    ("Top export buttons start disabled", 'id="downloadSemanticTopBtn" class="secondary-btn" disabled' in index and 'id="downloadEngineTopBtn" class="secondary-btn" disabled' in index),
    ("Semantic download endpoint exists", '@app.get("/api/ifc/semantic/download")' in app),
    ("Engine download endpoint exists", '@app.get("/api/ifc/semantic/engine-download")' in app),
    ("Engine download uses geometry_ifc_v03.json filename", 'filename="geometry_ifc_v03.json"' in app),
    ("Export buttons follow committed semantic state after generation",
     'setExportReady(committedCurrent);' in appjs
     and "result.semantic_state?.status === 'ready'" in appjs
     and 'result.stale === false' in appjs),
    ("Export buttons restore from project state", 'setExportReady(!state.semantic.stale);' in appjs),
    ("Selection change disables stale exports", 'setExportReady(false);' in appjs),
    ("Top Semantic button downloads endpoint", "startDownload('/api/ifc/semantic/download')" in appjs),
    ("Top Engine button downloads endpoint", "startDownload('/api/ifc/semantic/engine-download')" in appjs),
]

print("Export UI v0.3.1 Check")
print("=" * 60)
failed = 0
for name, ok in checks:
    print(("PASS" if ok else "FAIL") + ": " + name)
    failed += 0 if ok else 1
print("=" * 60)
if failed:
    print(f"EXPORT UI v0.3.1 CHECK: FAIL ({failed})")
    raise SystemExit(1)
print("EXPORT UI v0.3.1 CHECK: PASS")
