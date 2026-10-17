from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from fixture_paths import large_ifc_from_env


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent


def find_fixture() -> Path:
    search_roots = [PROJECT_ROOT, PROJECT_ROOT.parent]
    candidates = []
    for root in search_roots:
        candidates.extend([
            *([large_ifc_from_env()] if large_ifc_from_env() else []),
            *sorted(root.glob("*30*.ifc")),
            *sorted(root.glob("*.ifc")),
        ])
    seen = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists() and path.stat().st_size > 10_000_000:
            return path
    raise FileNotFoundError(
        "Large IFC fixture not found. Set VBB_LARGE_IFC to the large IFC path or put it in the project root."
    )


def scan_step(path: Path) -> Counter:
    counts: Counter[str] = Counter()
    pattern = re.compile(r"=\s*(IFC[A-Z0-9_]+)\(", re.I)
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = pattern.search(line)
            if m:
                counts[m.group(1).upper()] += 1
    return counts


def main() -> int:
    path = find_fixture()
    counts = scan_step(path)

    expected = {
        "IFCBUILDINGSTOREY": 36,
        "IFCWALLSTANDARDCASE": 920,
        "IFCSLAB": 1112,
        "IFCCOLUMN": 434,
        "IFCBEAM": 1067,
        "IFCSTAIR": 3,
        "IFCSTAIRFLIGHT": 4,
        "IFCOPENINGELEMENT": 14,
        "IFCDOOR": 0,
        "IFCWINDOW": 0,
        "IFCRELFILLSELEMENT": 0,
        "IFCRELVOIDSELEMENT": 14,
    }

    print("Large IFC Fixture v0.4.1 - STEP Scan")
    print("=" * 68)
    print(f"File: {path}")
    print(f"Size: {path.stat().st_size / (1024 * 1024):.2f} MB")

    failures = 0
    for key, value in expected.items():
        actual = counts.get(key, 0)
        ok = actual == value
        print(f"{'PASS' if ok else 'FAIL'}: {key} = {actual} (expected {value})")
        failures += 0 if ok else 1

    print("=" * 68)
    if failures:
        print(f"LARGE IFC FIXTURE CHECK: FAIL ({failures} mismatch(es))")
        return 1
    print("LARGE IFC FIXTURE CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
