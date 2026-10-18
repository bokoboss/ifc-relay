"""Run semantic JSON through the external Geometry Engine (validate-only).

Uses the engine found by project_paths.engine_path() (bundled engine/ copy,
or VBB_GEOMETRY_ENGINE / local override). Skipped only if no engine exists.
No Vissim/COM and no base network are needed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ifc_semantic_service import write_semantic_model

ROOT = Path(__file__).resolve().parent.parent
from project_paths import engine_path

ENGINE = engine_path()

requires_engine = pytest.mark.skipif(not ENGINE.exists(), reason=f"engine not found: {ENGINE}")


def engine_validate(semantic: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    project = tmp_path / "engine_root"
    project.mkdir(exist_ok=True)
    sem_path = tmp_path / "geometry.json"
    val_path = tmp_path / "validation.json"
    write_semantic_model(sem_path, semantic)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "40_vissim_build_adapter_v04.py"),
         "--project-root", str(project), "--input", str(sem_path),
         "--validation-output", str(val_path), "--validate-only", "--engine", str(ENGINE)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (proc.stderr or proc.stdout)[-2000:]
    return json.loads(val_path.read_text(encoding="utf-8"))


def issue_types(validation: dict[str, Any]) -> list[str]:
    return [i["type"] for i in validation["issues"] if i["severity"] != "info"]
