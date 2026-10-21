"""Qualify the installed Vissim releases for IFC Relay builds (Windows).

Run through qualify_vissim.bat. For each Vissim release registered on this
machine (or the ones given with --release):

1. Build the synthetic verification model (the one verify_vissim.bat uses:
   straight stair, U-stair with landing, partial flight, door-less opening,
   L-shaped wall, closed wall loop) with that release only - no fallback.
2. Optionally build a real IFC too (--ifc; stairs included, other elements
   by the app's default rules).
3. Reopen each .inpx in the same release and read back every level, area,
   obstacle and ramp/stair; compare with what the Geometry Engine reported
   it created (level, height, z offsets within 1 mm).
4. With two or more releases, compare the read-backs with each other.

Report: <project root>/output/qualify_<timestamp>/report.md (+ report.json).
With --redact the real IFC's file name and folder paths are left out of the
report. Nothing in the repository or the source IFC is modified.
"""
from __future__ import annotations

import argparse
import json
import os
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


def semantic_for_verification(out_dir: Path) -> Path:
    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model, write_semantic_model
    from verify_vissim import build_verification_ifc

    ifc = out_dir / "verify_model.ifc"
    overrides = build_verification_ifc(ifc)
    sem = build_semantic_model(ifc, extract_ifc_geometry(ifc), overrides)
    path = out_dir / "verify_model_geometry.json"
    write_semantic_model(path, sem)
    return path


def semantic_for_ifc(ifc: Path, out_dir: Path) -> Path:
    import ifcopenshell

    from ifc_geometry_service import extract_ifc_geometry
    from ifc_semantic_service import build_semantic_model, write_semantic_model

    model = ifcopenshell.open(str(ifc))
    overrides = {e.GlobalId: "include" for cls in ("IfcStair", "IfcStairFlight", "IfcRamp", "IfcRampFlight")
                 for e in model.by_type(cls) if getattr(e, "GlobalId", None)}
    sem = build_semantic_model(ifc, extract_ifc_geometry(ifc), overrides)
    path = out_dir / "real_model_geometry.json"
    write_semantic_model(path, sem)
    return path


def qualify_one(prog_id: str, label: str, semantic_path: Path, root: Path) -> dict[str, Any]:
    """Build with exactly ``prog_id``, reopen, read back, compare."""
    from vissim_build_service import build_vissim_model, validate_engine_input
    from vissim_readback import compare, read_network

    row: dict[str, Any] = {"prog_id": prog_id, "model": label}
    os.environ["VBB_VISSIM_PROGID"] = prog_id          # explicit choice: the only candidate, no fallback
    try:
        validation = validate_engine_input(APP_DIR, root, semantic_path)
        row["engine_errors"] = (validation.get("severity_counts") or {}).get("error", 0)
        if not validation.get("build_allowed"):
            row.update(status="FAIL", detail="Geometry Engine does not allow the build")
            return row
        started = time.time()
        result = build_vissim_model(APP_DIR, root, semantic_path, f"qualify_{label}.ifc")
        row["build_sec"] = round(time.time() - started, 1)
        row["output_path"] = result["output_path"]
        engine_report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
        started = time.time()
        readback = read_network(prog_id, result["output_path"])
        row["readback_sec"] = round(time.time() - started, 1)
        row["readback"] = readback
        check = compare(engine_report, readback)
        row["counts"] = check["counts"]
        row["findings"] = check["findings"]
        fails = [f for f in check["findings"] if f["severity"] == "fail"]
        row["status"] = "PASS" if check["passed"] else "FAIL"
        row["detail"] = (f"{len(fails)} difference(s) after reopening" if fails
                         else "reopened file matches the engine report")
    except Exception as exc:  # noqa: BLE001 - one release failing must not stop the others
        row.update(status="FAIL", detail=f"{type(exc).__name__}: {str(exc)[-500:]}",
                   traceback=traceback.format_exc()[-4000:])
    finally:
        os.environ.pop("VBB_VISSIM_PROGID", None)
    return row


def write_report(out_dir: Path, rows: list[dict[str, Any]], cross: list[dict[str, Any]],
                 meta: dict[str, Any], redact: bool) -> Path:
    def where(path: str | None) -> str:
        return "(hidden)" if redact or not path else f"`{path}`"

    lines = ["# IFC Relay - Vissim release qualification", "",
             f"Run: {meta['run']}  ", f"App: {meta['app_version']}  ",
             f"Registered releases: {', '.join(meta['registered']) or 'none'}", "",
             "## Builds and read-back", "",
             "| Release | Model | Result | Build (s) | Levels | Areas | Obstacles | Ramps/stairs | Detail |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        c = r.get("counts") or {}

        def cell(name: str, c: dict = c) -> str:
            x = c.get(name)
            return f"{x['found']}/{x['expected']}" if x else "-"
        lines.append(f"| {r['prog_id']} | {r['model']} | **{r['status']}** | {r.get('build_sec', '-')} | "
                     f"{cell('levels')} | {cell('areas')} | {cell('obstacles')} | {cell('ramps')} | "
                     f"{str(r.get('detail', '')).replace('|', '/')} |")
    lines += ["", "Counts are objects found in the reopened file / objects the engine reported creating.", ""]
    for r in rows:
        fails = [f for f in r.get("findings") or [] if f["severity"] == "fail"]
        extra = [f for f in r.get("findings") or [] if f["kind"] == "extra"]
        if fails or extra:
            lines += [f"### {r['prog_id']} · {r['model']}", ""]
            for f in fails[:40]:
                what = f"{f['field']}: expected {f['expected']}, file has {f['actual']}" if f["kind"] == "mismatch" else "missing"
                lines.append(f"- {f['collection']} {f['key']}: {what}")
            if len(fails) > 40:
                lines.append(f"- ... {len(fails) - 40} more (report.json)")
            if extra:
                lines.append(f"- info: {len(extra)} object(s) in the file that this build did not create "
                             "(usually already in base_empty.inpx)")
            lines.append("")
    if cross:
        lines += ["## Release against release", "", "| Model | Releases | Result | Differences |", "| --- | --- | --- | --- |"]
        for c in cross:
            lines.append(f"| {c['model']} | {c['a']} vs {c['b']} | **{'SAME' if not c['diffs'] else 'DIFFERENT'}** | "
                         f"{'; '.join(c['diffs'][:5]).replace('|', '/') or '-'} |")
        lines.append("")
    lines += ["## Output files", ""]
    for r in rows:
        lines.append(f"- {r['prog_id']} · {r['model']}: {where(r.get('output_path'))}")
    lines += ["", "A PASS means the reopened file holds what the engine built. It does not replace an engineer's "
              "look at the model in Viswalk (stair directions, routes, simulation).", ""]
    md = out_dir / "report.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    slim = [{k: v for k, v in r.items() if k not in ("readback",) and not (redact and k == "output_path")} for r in rows]
    (out_dir / "report.json").write_text(json.dumps({"meta": meta, "runs": slim, "cross_release": cross},
                                                    indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return md


def main() -> int:
    from version import APP_VERSION
    from vissim_com import registered_releases
    from vissim_readback import same_network

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release", action="append", type=int,
                        help="Vissim release to qualify (repeatable); default: every registered one")
    parser.add_argument("--ifc", help="also build and check this real IFC (stairs included)")
    parser.add_argument("--redact", action="store_true", help="leave the IFC name and folder paths out of the report")
    parser.add_argument("--no-open", action="store_true", help="do not open the report folder at the end")
    args = parser.parse_args()

    root = project_root()
    registered = registered_releases()
    releases = args.release or registered
    out_dir = root / "output" / f"qualify_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print("IFC Relay - Vissim release qualification")
    print("=" * 64)
    problems = []
    if os.name != "nt":
        problems.append("needs Windows (Vissim COM)")
    if not engine_path().exists():
        problems.append(f"Geometry Engine not found: {engine_path()}")
    if not (root / BASE_NETWORK_FILE).exists():
        problems.append(f"{BASE_NETWORK_FILE} not found in {root}")
    if not releases:
        problems.append("no Vissim 2025/2026 COM server registered")
    if problems:
        for p in problems:
            print("[FAIL]", p)
        return 1

    models = [("verification", semantic_for_verification(out_dir))]
    if args.ifc:
        ifc = Path(args.ifc).expanduser().resolve()
        models.append(("real IFC" if args.redact else ifc.stem, semantic_for_ifc(ifc, out_dir)))

    rows = []
    for release in releases:
        prog_id = f"Vissim.Vissim.{release}"
        for label, sem in models:
            print(f"-> {prog_id} · {label}: build, reopen, read back (Vissim opens; this takes a while)...")
            row = qualify_one(prog_id, label, sem, root)
            print(f"[{row['status']}] {prog_id} · {label} - {row.get('detail', '')}")
            rows.append(row)

    cross = []
    for label, _ in models:
        done = [r for r in rows if r["model"] == label and r.get("readback")]
        for a, b in zip(done, done[1:]):
            cross.append({"model": label, "a": a["prog_id"], "b": b["prog_id"],
                          "diffs": same_network(a["readback"], b["readback"])})

    meta = {"run": f"{datetime.now():%Y-%m-%d %H:%M}", "app_version": APP_VERSION,
            "registered": [f"Vissim.Vissim.{r}" for r in registered],
            "qualified": [f"Vissim.Vissim.{r}" for r in releases]}
    md = write_report(out_dir, rows, cross, meta, args.redact)
    failed = any(r["status"] != "PASS" for r in rows) or any(c["diffs"] for c in cross)
    print("=" * 64)
    print("RESULT:", "FAIL" if failed else "PASS")
    print("Report:", md)
    if not args.no_open and os.name == "nt":
        try:
            os.startfile(str(out_dir))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
