"""Run semantic JSON through the external Geometry Engine (validate-only).

The engine (05_geometry_engine_v03.py) is not distributed with this repo.
Point VBB_GEOMETRY_ENGINE at a local copy to enable these checks; they are
skipped otherwise (e.g. in public CI). No Vissim/COM is needed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ifc_semantic_service import write_semantic_model

ROOT = Path(__file__).resolve().parent.parent
ENGINE = os.environ.get("VBB_GEOMETRY_ENGINE", "").strip()

requires_engine = pytest.mark.skipif(
    not ENGINE or not Path(ENGINE).exists(),
    reason="set VBB_GEOMETRY_ENGINE to a local 05_geometry_engine_v03.py",
)


def engine_validate(semantic: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    project = tmp_path / "engine_root"
    project.mkdir(exist_ok=True)
    shutil.copyfile(ENGINE, project / "05_geometry_engine_v03.py")
    (project / "base_empty.inpx").touch()  # existence check only in validate-only mode
    sem_path = tmp_path / "geometry.json"
    val_path = tmp_path / "validation.json"
    write_semantic_model(sem_path, semantic)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "40_vissim_build_adapter_v04.py"),
         "--project-root", str(project), "--input", str(sem_path),
         "--validation-output", str(val_path), "--validate-only"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (proc.stderr or proc.stdout)[-2000:]
    return json.loads(val_path.read_text(encoding="utf-8"))


def issue_types(validation: dict[str, Any]) -> list[str]:
    return [i["type"] for i in validation["issues"] if i["severity"] != "info"]
