"""Release qualification: read-back comparison and report (no Vissim needed)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from vissim_readback import compare, same_network

ROOT = Path(__file__).resolve().parents[1]

REPORT = {
    "levels": [{"key": 1, "name": "L1", "z": 0.0}, {"key": 2, "name": "L2", "z": 3.4},
               {"key": 901, "name": "Landing", "z": 1.7}],
    "areas": [{"key": 1001, "level_key": 1}, {"key": 1002, "level_key": 2}],
    "vissim_obstacles": [{"key": 1401, "level_key": 1, "height": 3.0, "z_offset": 0.0}],
    "vertical_connections": [{"key": 2001, "start_level": 1, "end_level": 901,
                              "start_z_offset": 0.0, "end_z_offset": -0.25}],
}


def _readback(**changes):
    rb = {
        "levels": [{"No": 1, "Name": "L1", "zCoord": 0.0}, {"No": 2, "Name": "L2", "zCoord": 3.4000004},
                   {"No": 901, "Name": "Landing", "zCoord": 1.7}],
        "areas": [{"No": 1001, "Level": "1"}, {"No": 1002, "Level": 2.0}],      # releases differ in type
        "obstacles": [{"No": 1401, "Level": 1, "Height": 3.0, "zOffsetB": 0.0}],
        "ramps": [{"No": 2001, "StartLvl": 1, "EndLvl": "901", "StartZOffset": 0.0, "EndZOffset": -0.25}],
    }
    rb.update(changes)
    return rb


def test_reopened_file_matching_the_engine_report_passes():
    check = compare(REPORT, _readback())
    assert check["passed"], check["findings"]
    assert check["counts"]["ramps"] == {"expected": 1, "found": 1, "in_file": 1}


def test_missing_object_and_changed_offset_fail_extra_is_info():
    rb = _readback(areas=[{"No": 1001, "Level": 1}, {"No": 7, "Level": 1}],
                   ramps=[{"No": 2001, "StartLvl": 1, "EndLvl": 901, "StartZOffset": 0.0, "EndZOffset": 0.0}])
    check = compare(REPORT, rb)
    assert not check["passed"]
    kinds = {(f["kind"], f["collection"], f["key"], f.get("field")) for f in check["findings"]}
    assert ("missing", "areas", 1002, None) in kinds
    assert ("mismatch", "ramps", 2001, "EndZOffset") in kinds
    assert ("extra", "areas", 7, None) in kinds
    assert next(f for f in check["findings"] if f["kind"] == "extra")["severity"] == "info"


def test_release_against_release():
    assert same_network(_readback(), _readback()) == []
    other = _readback(levels=[{"No": 1, "Name": "L1", "zCoord": 0.0}, {"No": 2, "Name": "L2", "zCoord": 3.5}])
    diffs = same_network(_readback(), other)
    assert "levels 2 zCoord: 3.4000004 vs 3.5" in diffs and any("901: only in first" in d for d in diffs)


def test_qualify_one_builds_with_exactly_that_release(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import qualify_vissim
    import vissim_build_service
    import vissim_readback

    seen = {}
    report_path = tmp_path / "engine_report.json"
    report_path.write_text(json.dumps(REPORT), encoding="utf-8")

    def fake_build(app_dir, root, sem, name):
        seen["prog"] = os.environ.get("VBB_VISSIM_PROGID")
        return {"output_path": str(tmp_path / "x.inpx"), "report_path": str(report_path)}

    monkeypatch.setattr(vissim_build_service, "validate_engine_input",
                        lambda *a: {"build_allowed": True, "severity_counts": {}})
    monkeypatch.setattr(vissim_build_service, "build_vissim_model", fake_build)
    monkeypatch.setattr(vissim_readback, "read_network", lambda prog, path: _readback())
    monkeypatch.delenv("VBB_VISSIM_PROGID", raising=False)

    row = qualify_vissim.qualify_one("Vissim.Vissim.2025", "verification", tmp_path / "sem.json", tmp_path)
    assert row["status"] == "PASS", row
    assert seen["prog"] == "Vissim.Vissim.2025"                 # no fallback to another release
    assert "VBB_VISSIM_PROGID" not in os.environ                # restored afterwards

    rows = [row, {**row, "prog_id": "Vissim.Vissim.2026"}]
    md = qualify_vissim.write_report(tmp_path, rows, [{"model": "verification", "a": "Vissim.Vissim.2025",
                                                       "b": "Vissim.Vissim.2026", "diffs": []}],
                                     {"run": "now", "app_version": "x", "registered": []}, redact=True)
    text = md.read_text(encoding="utf-8")
    assert "**PASS**" in text and "**SAME**" in text and "1/1" in text
    assert str(tmp_path) not in text                            # redacted: no folder paths
    assert str(tmp_path) not in (tmp_path / "report.json").read_text(encoding="utf-8")
