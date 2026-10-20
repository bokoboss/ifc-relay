"""One-command verification on a Windows machine with PTV Vissim 2025.

Run through verify_vissim.bat. Steps:

1. Environment: Python packages, engine / base network location, Vissim COM.
2. Automated tests (synthetic IFC) including engine-contract tests.
3. Fixture #1 regression (checks/36_check_ifc_semantic_v03.py) if TallBuilding.ifc
   is available (VBB_FIXTURE1_IFC or the project root).
4. Vissim COM build of a synthetic verification model that exercises the
   v0.5 work: straight stair, U-stair with landing level, flight ending
   between levels, L-shaped wall, closed wall loop, door-less opening.
5. Report (report.md + report.json) with a manual checklist for Vissim.

Nothing in the repository or the source IFCs is modified; all outputs go to
<project root>/output/verify_<timestamp>/.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from project_paths import BASE_NETWORK_FILE, engine_path, project_root  # noqa: E402

PROG_ID = "VISSIM.Vissim.2025"


class Report:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.steps: list[dict[str, Any]] = []
        self.data: dict[str, Any] = {}

    def add(self, name: str, status: str, detail: str = "") -> None:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP", "WARN": "WARN"}[status]
        print(f"[{mark}] {name}" + (f" - {detail}" if detail else ""))
        self.steps.append({"step": name, "status": status, "detail": detail})

    def failed(self) -> bool:
        return any(s["status"] == "FAIL" for s in self.steps)


def vissim_com_registered() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, PROG_ID))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 1. Environment
# ---------------------------------------------------------------------------

def check_environment(rep: Report, root: Path) -> dict[str, Any]:
    env: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "app_dir": str(APP_DIR),
        "project_root": str(root),
    }
    missing = []
    for mod in ("fastapi", "ifcopenshell", "shapely", "numpy", "pytest"):
        try:
            m = importlib.import_module(mod)
            env[mod] = str(getattr(m, "__version__", getattr(m, "version", "ok")))
        except Exception:
            missing.append(mod)
    rep.add("Python packages", "FAIL" if missing else "PASS",
            f"missing: {', '.join(missing)}" if missing else f"Python {env['python']}")

    engine = engine_path()
    base = root / BASE_NETWORK_FILE
    env["engine_found"] = engine.exists()
    env["base_network_found"] = base.exists()
    rep.add("Geometry Engine", "PASS" if engine.exists() else "FAIL", str(engine))
    rep.add("Vissim base network", "PASS" if base.exists() else "FAIL", str(base))

    com = vissim_com_registered()
    env["vissim_com_registered"] = com
    rep.add(f"Vissim COM ({PROG_ID})", "PASS" if com else "FAIL",
            "registered" if com else "ProgID not found; is Vissim 2025 installed?")
    rep.data["environment"] = env
    return env


# ---------------------------------------------------------------------------
# 2. Automated tests
# ---------------------------------------------------------------------------

def run_pytest(rep: Report, root: Path) -> None:
    env = dict(os.environ)
    engine = engine_path()
    if engine.exists():
        env["VBB_GEOMETRY_ENGINE"] = str(engine)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests"],
        cwd=APP_DIR, env=env, capture_output=True, text=True,
    )
    tail = (proc.stdout or proc.stderr).strip().splitlines()
    summary = tail[-1] if tail else ""
    (rep.out_dir / "pytest.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    skipped_engine = "skipped" in summary and engine.exists()
    status = "PASS" if proc.returncode == 0 and not skipped_engine else ("WARN" if proc.returncode == 0 else "FAIL")
    rep.add("Automated tests (incl. engine contract)", status, summary)


# ---------------------------------------------------------------------------
# 3. Fixture #1
# ---------------------------------------------------------------------------

def run_fixture1(rep: Report, root: Path) -> None:
    ifc = Path(os.environ["VBB_FIXTURE1_IFC"]) if os.environ.get("VBB_FIXTURE1_IFC") else root / "TallBuilding.ifc"
    if not ifc.exists():
        rep.add("Fixture #1 regression (36)", "SKIP", f"not found: {ifc} (set VBB_FIXTURE1_IFC)")
        return
    env = dict(os.environ, VBB_FIXTURE1_IFC=str(ifc), VBB_PROJECT_ROOT=str(root))
    proc = subprocess.run(
        [sys.executable, "checks/36_check_ifc_semantic_v03.py"],
        cwd=APP_DIR, env=env, capture_output=True, text=True,
    )
    (rep.out_dir / "fixture1.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    fails = [line for line in proc.stdout.splitlines() if line.startswith("FAIL")]
    rep.add("Fixture #1 regression (36)", "PASS" if proc.returncode == 0 else "FAIL",
            "; ".join(fails[:3]) if fails else "5 levels / 4 areas / 24-29 walls / 29 obstacles")


# ---------------------------------------------------------------------------
# 4. Synthetic verification model -> Vissim COM build
# ---------------------------------------------------------------------------

def build_verification_ifc(path: Path) -> dict[str, str]:
    from shapely.geometry import Polygon, box

    from ifc_semantic_service import split_out_holes
    from tests.ifc_factory import Building, add_opening, add_wall

    H = 3.4
    b = Building([0.0, H])
    l1, l2 = b.storeys
    b.slab([(0, 0), (30, 0), (30, 20), (0, 20)], 0.0, l1)

    # Upper floor with stairwells over the straight stair and the U-stair.
    upper = box(0, 0, 30, 20).difference(box(2, 1, 8, 2.2)).difference(box(12, 1, 17.5, 3.6))
    parts = upper.geoms if hasattr(upper, "geoms") else [upper]
    for part in parts:
        for piece in split_out_holes(part):
            b.slab(list(piece.exterior.coords)[:-1], H, l2)

    # A: straight stair L1 -> L2 (rises towards +x)
    straight = b.stair(l1, name="VERIFY straight stair")
    b.flight(2.0, 8.0, 1.0, 2.2, 0.0, H, parent=straight)

    # B: U-stair with intermediate landing
    u = b.stair(l1, name="VERIFY U-stair")
    b.flight(12.0, 16.0, 1.0, 2.2, 0.0, H / 2, parent=u)
    b.flight(16.0, 12.0, 2.4, 3.6, H / 2, H, parent=u)
    b.slab([(16, 1), (17.5, 1), (17.5, 3.6), (16, 3.6)], H / 2, None, predefined="LANDING", parent=u)

    # C: flight ending between levels (top at +1.20 m)
    partial = b.flight(22.0, 25.0, 1.0, 2.2, 0.0, 1.2, storey=l1, Name="VERIFY partial flight")

    # D: straight wall with a door-less opening that the engineer opens
    wall = add_wall(b, 1.0, 10.0, 12.0, l1)
    opening = add_opening(b, wall, 6.0, 7.0, 10.0, 0.0, 2.1)

    # E: L-shaped wall
    pts = [(16, 8), (20, 8), (20, 8.2), (16.2, 8.2), (16.2, 12), (16, 12)]
    n = len(pts)
    b.mesh_element("IfcWall", [(x, y, 0) for x, y in pts] + [(x, y, 3) for x, y in pts],
                   [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
                   + [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)], storey=l1)

    # F: closed wall loop around a shaft
    verts, faces = [], []
    for x0, y0, x1, y1 in [(22, 8, 26, 8.2), (22, 10.8, 26, 11), (22, 8.2, 22.2, 10.8), (25.8, 8.2, 26, 10.8)]:
        k = len(verts)
        verts += [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0),
                  (x0, y0, 3), (x1, y0, 3), (x1, y1, 3), (x0, y1, 3)]
        faces += [(k, k + 3, k + 2, k + 1), (k + 4, k + 5, k + 6, k + 7), (k, k + 1, k + 5, k + 4),
                  (k + 1, k + 2, k + 6, k + 5), (k + 2, k + 3, k + 7, k + 6), (k + 3, k, k + 4, k + 7)]
    b.mesh_element("IfcWall", verts, faces, storey=l1)

    b.write(path)
    return {
        straight.GlobalId: "include",
        u.GlobalId: "include",
        partial.GlobalId: "include",
        opening.GlobalId: "include",
    }


def run_vissim_build(rep: Report, root: Path, skip_build: bool) -> None:
    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model, write_semantic_model
    from vissim_build_service import build_vissim_model, validate_engine_input

    ifc_path = rep.out_dir / "verify_model.ifc"
    try:
        overrides = build_verification_ifc(ifc_path)
        geometry = extract_ifc_geometry(ifc_path)
        semantic = build_semantic_model(ifc_path, geometry, overrides)
        sem_path = rep.out_dir / "verify_model_geometry.json"
        write_semantic_model(sem_path, semantic)
    except Exception as exc:
        rep.add("Verification model -> semantic JSON", "FAIL", f"{type(exc).__name__}: {exc}")
        (rep.out_dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        return

    summary = semantic["ifc_semantic"]["summary"]
    rep.data["semantic_summary"] = summary
    rep.data["vertical_connections"] = [
        {k: v.get(k) for k in ("key", "name", "type", "start_level", "end_level",
                               "start_z_offset", "end_z_offset", "steps", "bottom_edge", "top_edge")}
        for v in semantic["vertical_connections"]
    ]
    rep.data["levels"] = semantic["levels"]
    expected = summary["vertical_connections"] == 4 and summary["generated_landing_levels"] == 1 \
        and summary["polygon_walls"] == 2 and summary["unfilled_openings_applied"] == 1
    rep.add("Verification model -> semantic JSON", "PASS" if expected else "FAIL",
            f"{summary['vertical_connections']} vertical, {summary['generated_landing_levels']} landing level, "
            f"{summary['polygon_walls']} polygon walls, {summary['unfilled_openings_applied']} opened door-less opening")

    if not engine_path().exists():
        rep.add("Engine validation", "SKIP", "engine not found")
        rep.add("Vissim COM build", "SKIP", "engine not found")
        return
    try:
        validation = validate_engine_input(APP_DIR, root, sem_path)
        counts = validation["severity_counts"]
        status = "PASS" if validation["build_allowed"] and counts.get("warning", 0) == 0 else (
            "WARN" if validation["build_allowed"] else "FAIL")
        rep.add("Engine validation", status, f"errors={counts.get('error', 0)} warnings={counts.get('warning', 0)}")
        rep.data["engine_validation"] = validation
    except Exception as exc:
        rep.add("Engine validation", "FAIL", str(exc)[-400:])
        return

    if skip_build:
        rep.add("Vissim COM build", "SKIP", "--skip-build")
        return
    if os.name != "nt" or not vissim_com_registered() or not (root / BASE_NETWORK_FILE).exists():
        rep.add("Vissim COM build", "SKIP", "needs Windows, Vissim 2025 COM and base_empty.inpx")
        return

    print("Building .inpx through Vissim COM (Vissim will open; this can take a minute)...")
    started = time.time()
    try:
        result = build_vissim_model(APP_DIR, root, sem_path, "verify_model.ifc")
        rep.data["build"] = {k: result[k] for k in ("output_path", "report_path", "log_path", "duration_sec")}
        rep.add("Vissim COM build", "PASS", f"{result['output_path']} ({time.time() - started:.0f} s)")
    except Exception as exc:
        rep.add("Vissim COM build", "FAIL", str(exc)[-600:])


# ---------------------------------------------------------------------------
# 5. Report
# ---------------------------------------------------------------------------

MANUAL_CHECKS = [
    "Open the built .inpx in Vissim 2025 (path above).",
    "Levels: L1 (0.00), L2 (3.40) and one generated landing level (+1.70) exist.",
    "Straight stair (x 2-8, y 1-2.2): starts on L1 at x = 2 and ends on L2 at x = 8. "
    "If Vissim shows it reversed, the start edge convention is the opposite of bottom-edge-first.",
    "U-stair: flight 1 L1 -> landing (x 12-16), landing area at +1.70, flight 2 landing -> L2 (x 16-12).",
    "Partial flight (x 22-25): Vissim accepted the negative EndZOffset (top at +1.20 m).",
    "Wall at y = 10 has a 1 m gap at x 6-7 (door-less opening that was ticked).",
    "L-shaped wall (x 16-20, y 8-12) does not block its inside corner.",
    "Closed wall loop (x 22-26, y 8-11) is a ring, not a solid block.",
    "Optional: add a pedestrian input on L1 and a route to L2; pedestrians use both stairs.",
]


def write_report(rep: Report) -> Path:
    lines = [
        "# Viswalk BIM Builder - Vissim verification",
        "",
        f"Run: {datetime.now():%Y-%m-%d %H:%M}",
        f"Project root: `{rep.data.get('environment', {}).get('project_root', '')}`",
        "",
        "## Automated steps",
        "",
        "| Step | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for s in rep.steps:
        detail = s["detail"].replace("|", "/").replace("\n", " ")
        lines.append(f"| {s['step']} | **{s['status']}** | {detail} |")
    if rep.data.get("vertical_connections"):
        lines += ["", "## Vertical connections sent to Vissim", "",
                  "| Key | Name | Type | Start -> End | Offsets (m) | Bottom edge (x, y) |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for v in rep.data["vertical_connections"]:
            be = v.get("bottom_edge") or [[0, 0], [0, 0]]
            mid = ((be[0][0] + be[1][0]) / 2, (be[0][1] + be[1][1]) / 2)
            lines.append(
                f"| {v['key']} | {v['name']} | {v['type']} | {v['start_level']} -> {v['end_level']} | "
                f"{v['start_z_offset']:+.2f} / {v['end_z_offset']:+.2f} | ({mid[0]:.2f}, {mid[1]:.2f}) |"
            )
    lines += ["", "## Manual checks in Vissim", ""] + [f"- [ ] {c}" for c in MANUAL_CHECKS]
    lines += ["", "Logs: `pytest.log`, `fixture1.log` (if run), engine report and build log in the build folder.", ""]
    md = rep.out_dir / "report.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    (rep.out_dir / "report.json").write_text(
        json.dumps({"steps": rep.steps, **rep.data}, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return md


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-build", action="store_true", help="do everything except the Vissim COM build")
    parser.add_argument("--no-open", action="store_true", help="do not open the report folder at the end")
    parser.add_argument("--ifc", help="dry-run a real IFC (audit -> geometry -> semantic -> engine validation), no Vissim needed")
    parser.add_argument("--redact", action="store_true", help="with --ifc: remove file/project/storey names and paths from the report")
    parser.add_argument("--stairs-review-only", action="store_true",
                        help="with --ifc: keep stairs review-only (app default) instead of including all stairs")
    args = parser.parse_args()

    if args.ifc:
        from ifc_dry_run import run_ifc_check

        if not args.skip_build:
            print("Note: --ifc runs a dry run only (no Vissim build). Use the app to build a real model.")
        overall, md = run_ifc_check(Path(args.ifc), include_stairs=not args.stairs_review_only, redact=args.redact)
        if not args.no_open and os.name == "nt":
            try:
                os.startfile(str(md.parent))  # type: ignore[attr-defined]
            except Exception:
                pass
        return 1 if overall == "FAIL" else 0

    root = project_root()
    out_dir = root / "output" / f"verify_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = Report(out_dir)

    print("Viswalk BIM Builder - verification on this machine")
    print("=" * 64)
    check_environment(rep, root)
    run_pytest(rep, root)
    run_fixture1(rep, root)
    run_vissim_build(rep, root, args.skip_build)
    md = write_report(rep)

    print("=" * 64)
    print("RESULT:", "FAIL" if rep.failed() else "PASS (complete the manual checks in report.md)")
    print("Report:", md)
    if not args.no_open and os.name == "nt":
        try:
            os.startfile(str(out_dir))  # type: ignore[attr-defined]
        except Exception:
            pass
    return 1 if rep.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
