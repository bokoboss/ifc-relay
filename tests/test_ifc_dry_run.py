from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ifc_dry_run import classify_warning, run_ifc_check, sha256_of  # noqa: E402
from tests.engine_contract import requires_engine  # noqa: E402
from tests.ifc_factory import Building, add_opening, add_wall  # noqa: E402

H = 3.4


def _building(names: dict[str, str] | None = None) -> Building:
    b = Building([0.0, H])
    if names:
        b.project.Name = names["project"]
        for i, s in enumerate(b.storeys, start=1):
            s.Name = f"{names['storey']} {i}"
    l1, l2 = b.storeys
    b.slab([(0, 0), (20, 0), (20, 10), (0, 10)], 0.0, l1)
    for poly in ([(0, 0), (20, 0), (20, 1), (0, 1)], [(0, 2.2), (20, 2.2), (20, 10), (0, 10)],
                 [(0, 1), (2, 1), (2, 2.2), (0, 2.2)], [(8, 1), (20, 1), (20, 2.2), (8, 2.2)]):
        b.slab(poly, H, l2)
    stair = b.stair(l1)
    b.flight(2.0, 8.0, 1.0, 2.2, 0.0, H, parent=stair)
    wall = add_wall(b, 1.0, 6.0, 12.0, l1)
    add_opening(b, wall, 5.0, 6.0, 6.0, 0.0, 2.1)
    b.box("IfcColumn", 15, 5, 15.4, 5.4, 0.0, 3.0, l1)
    return b


def test_classify_warning_reasons():
    assert classify_warning("Included slab X has no cached mesh.")[0] == "skipped"
    assert classify_warning("1 wall opening(s) without a door look walkable ...")[0] == "review"
    assert classify_warning("something unexpected")[0] == "other"


@requires_engine
def test_dry_run_report_contents_and_source_unchanged(tmp_path):
    ifc = _building().write(tmp_path / "plain.ifc")
    before = sha256_of(ifc)
    overall, md = run_ifc_check(ifc, out_dir=tmp_path / "report")
    data = json.loads((md.parent / "report.json").read_text(encoding="utf-8"))

    assert sha256_of(ifc) == before
    assert data["source"]["unchanged"] is True
    assert overall in ("PASS", "WARN")
    names = [s["step"] for s in data["steps"]]
    assert names == [
        "Environment (Python packages, Geometry Engine)", "Import source IFC (read-only)", "IFC audit",
        "Geometry extraction (simulation-relevant)", "Semantic conversion (pedestrian model)",
        "Geometry Engine validation", "Source IFC unchanged",
    ]
    assert all("seconds" in s for s in data["steps"])
    c = data["ifc"]["counts"]
    assert (c["storeys"], c["walls"], c["stairs"], c["stair_flights"], c["openings"], c["columns"]) == (2, 1, 1, 1, 1, 1)
    conv = data["semantic"]["converted"]
    assert conv["vertical_connections"] == 1 and conv["walkable_areas"] >= 2 and conv["obstacles_total"] >= 2
    assert data["engine_validation"]["severity_counts"].get("error", 0) == 0
    assert data["environment"]["base_network_required"] is False
    # Report states the Viswalk limitation in both languages.
    text = md.read_text(encoding="utf-8")
    assert "ไม่ได้หมายความว่าผ่านการตรวจความถูกต้องใน Viswalk" in text and "does NOT mean" in text
    # Nothing written next to the IFC.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plain.ifc", "report"]
    assert (md.parent / "_private" / "semantic_geometry.json").exists()


@requires_engine
def test_stairs_review_only_option(tmp_path):
    ifc = _building().write(tmp_path / "b.ifc")
    _, md = run_ifc_check(ifc, out_dir=tmp_path / "r", include_stairs=False)
    data = json.loads((md.parent / "report.json").read_text(encoding="utf-8"))
    assert data["semantic"]["converted"]["vertical_connections"] == 0
    assert "review-only" in data["semantic"]["stairs_policy"]


@requires_engine
def test_redacted_report_has_no_project_names_or_paths(tmp_path):
    secret_dir = tmp_path / "ClientConfidentialFolder"
    secret_dir.mkdir()
    names = {"project": "Example Tower Project", "storey": "Example Level"}
    ifc = _building(names).write(secret_dir / "example_tower_rev7.ifc")
    _, md = run_ifc_check(ifc, out_dir=tmp_path / "r", redact=True)
    for f in ("report.md", "report.json"):
        text = (md.parent / f).read_text(encoding="utf-8")
        for secret in ("Example Tower", "example_tower_rev7", "ClientConfidentialFolder", str(tmp_path)):
            assert secret not in text, (f, secret)
    data = json.loads((md.parent / "report.json").read_text(encoding="utf-8"))
    assert data["redacted"] is True
    assert data["source"]["file_name"].startswith("IFC-")
    assert [s["name"] for s in data["ifc"]["storeys"]] == ["Storey 1", "Storey 2"]


def test_missing_file_fails_cleanly(tmp_path):
    overall, md = run_ifc_check(tmp_path / "nope.ifc", out_dir=tmp_path / "r")
    assert overall == "FAIL"
    data = json.loads((md.parent / "report.json").read_text(encoding="utf-8"))
    assert any(s["status"] == "FAIL" and "Import" in s["step"] for s in data["steps"])


@requires_engine
def test_verify_script_cli(tmp_path):
    ifc = _building().write(tmp_path / "cli.ifc")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_vissim.py"), "--ifc", str(ifc),
                           "--skip-build", "--no-open"], capture_output=True, text=True, cwd=ROOT,
                          env={**__import__("os").environ, "VBB_PROJECT_ROOT": str(tmp_path / "proj")})
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "RESULT:" in proc.stdout and "does NOT mean" in proc.stdout
