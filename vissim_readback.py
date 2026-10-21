"""Read a built .inpx back through Vissim COM and compare it with what the
Geometry Engine says it created (its ``*_geometry_engine_report.json``).

Used by scripts/qualify_vissim.py to qualify a Vissim release: the file is
reopened in the same release, and every level, area, obstacle and ramp/stair
the engine reports must exist with the same level, height and z offsets.
Collections and attribute names are the ones the engine itself writes.

``compare`` is pure (no COM) so it is unit-tested on any platform; only
``read_network`` needs Windows and Vissim.
"""
from __future__ import annotations

from typing import Any

# Collection -> (Vissim container, attributes read back)
ATTRS: dict[str, tuple[str, tuple[str, ...]]] = {
    "levels": ("Levels", ("No", "Name", "zCoord")),
    "areas": ("Areas", ("No", "Level")),
    "obstacles": ("Obstacles", ("No", "Level", "Height", "zOffsetB")),
    "ramps": ("Ramps", ("No", "StartLvl", "EndLvl", "StartZOffset", "EndZOffset")),
}

# Expected value per read-back attribute, from the engine report record.
# (collection in report, read-back collection, [(report field, Vissim attribute, numeric?)])
CHECKS: tuple[tuple[str, str, tuple[tuple[str, str, bool], ...]], ...] = (
    ("levels", "levels", (("z", "zCoord", True),)),
    ("areas", "areas", (("level_key", "Level", False),)),
    ("vissim_obstacles", "obstacles", (("level_key", "Level", False), ("height", "Height", True),
                                       ("z_offset", "zOffsetB", True))),
    ("vertical_connections", "ramps", (("start_level", "StartLvl", False), ("end_level", "EndLvl", False),
                                       ("start_z_offset", "StartZOffset", True),
                                       ("end_z_offset", "EndZOffset", True))),
)

TOLERANCE_M = 0.001


def read_network(prog_id: str, inpx_path: str) -> dict[str, Any]:
    """Open ``inpx_path`` in the Vissim release ``prog_id`` and read the four collections."""
    import win32com.client as com  # Windows only

    vissim = com.gencache.EnsureDispatch(prog_id)
    try:
        vissim.LoadNet(str(inpx_path))
        out: dict[str, Any] = {"prog_id": prog_id}
        for name, (container, attrs) in ATTRS.items():
            coll = getattr(vissim.Net, container)
            rows = []
            for obj in coll.GetAll():
                row = {}
                for attr in attrs:
                    try:
                        row[attr] = obj.AttValue(attr)
                    except Exception as exc:  # noqa: BLE001 - recorded, compared as missing
                        row[attr] = f"<error: {exc}>"
                rows.append(row)
            out[name] = rows
        return out
    finally:
        try:
            vissim.Exit()
        except Exception:  # noqa: BLE001
            pass


def _key(value: Any) -> Any:
    """Level references come back as numbers or strings depending on the release."""
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return str(value).strip()


def compare(engine_report: dict[str, Any], readback: dict[str, Any],
            tolerance: float = TOLERANCE_M) -> dict[str, Any]:
    """Findings where the reopened file differs from the engine report.

    ``missing``: the engine created it, the file does not have it (fail).
    ``mismatch``: same key, different level / height / z offset (fail).
    ``extra``: in the file but not created by this build, e.g. objects already in
    the base network (info).
    """
    findings: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for report_coll, rb_coll, fields in CHECKS:
        expected = {int(r["key"]): r for r in engine_report.get(report_coll) or []}
        actual = {_key(r.get("No")): r for r in readback.get(rb_coll) or []}
        counts[rb_coll] = {"expected": len(expected), "found": sum(1 for k in expected if k in actual),
                           "in_file": len(actual)}
        for key, rec in sorted(expected.items()):
            got = actual.get(key)
            if got is None:
                findings.append({"severity": "fail", "kind": "missing", "collection": rb_coll, "key": key})
                continue
            for field, attr, numeric in fields:
                want, have = rec.get(field), got.get(attr)
                if want is None:
                    continue
                if numeric:
                    try:
                        ok = abs(float(want) - float(have)) <= tolerance
                    except (TypeError, ValueError):
                        ok = False
                else:
                    ok = _key(want) == _key(have)
                if not ok:
                    findings.append({"severity": "fail", "kind": "mismatch", "collection": rb_coll, "key": key,
                                     "field": attr, "expected": want, "actual": have})
        for key in sorted((k for k in actual if k not in expected), key=str):
            findings.append({"severity": "info", "kind": "extra", "collection": rb_coll, "key": key})
    return {
        "passed": not any(f["severity"] == "fail" for f in findings),
        "counts": counts,
        "findings": findings,
    }


def same_network(a: dict[str, Any], b: dict[str, Any], tolerance: float = TOLERANCE_M) -> list[str]:
    """Differences between two read-backs of the same build input (release A vs B)."""
    diffs: list[str] = []
    for name, (_, attrs) in ATTRS.items():
        rows_a = {_key(r.get("No")): r for r in a.get(name) or []}
        rows_b = {_key(r.get("No")): r for r in b.get(name) or []}
        for key in sorted(set(rows_a) ^ set(rows_b), key=str):
            diffs.append(f"{name} {key}: only in {'first' if key in rows_a else 'second'}")
        for key in sorted(set(rows_a) & set(rows_b), key=str):
            for attr in attrs:
                if attr in ("No", "Name"):
                    continue
                va, vb = rows_a[key].get(attr), rows_b[key].get(attr)
                try:
                    same = abs(float(va) - float(vb)) <= tolerance
                except (TypeError, ValueError):
                    same = _key(va) == _key(vb)
                if not same:
                    diffs.append(f"{name} {key} {attr}: {va} vs {vb}")
    return diffs
