"""Where the app finds the Geometry Engine, the Vissim base network and outputs.

Geometry Engine (05_geometry_engine_v03.py), first match wins:
1. ``VBB_GEOMETRY_ENGINE`` environment variable (a file path).
2. ``<app>/local/05_geometry_engine_v03.py`` (local override).
3. ``<app>/engine/05_geometry_engine_v03.py`` (bundled with the repository).
4. ``<app>/../05_geometry_engine_v03.py`` (original parent-folder layout).

Project root (base_empty.inpx, Fixture #1, output/):
1. ``VBB_PROJECT_ROOT`` environment variable.
2. ``<app>/local`` if it contains base_empty.inpx or the engine.
3. The app's parent folder if it contains base_empty.inpx or the engine.
4. ``<app>/local`` (default for a fresh install).

base_empty.inpx is created with licensed Vissim and is never committed.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ENGINE_FILE = "05_geometry_engine_v03.py"
BASE_NETWORK_FILE = "base_empty.inpx"


def _has_local_assets(folder: Path) -> bool:
    return (folder / BASE_NETWORK_FILE).exists() or (folder / ENGINE_FILE).exists()


def project_root() -> Path:
    env = os.environ.get("VBB_PROJECT_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    local = APP_DIR / "local"
    if _has_local_assets(local):
        return local
    if _has_local_assets(APP_DIR.parent):
        return APP_DIR.parent
    return local


def engine_path() -> Path:
    env = os.environ.get("VBB_GEOMETRY_ENGINE", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    for candidate in (
        APP_DIR / "local" / ENGINE_FILE,
        APP_DIR / "engine" / ENGINE_FILE,
        APP_DIR.parent / ENGINE_FILE,
    ):
        if candidate.exists():
            return candidate
    return APP_DIR / "engine" / ENGINE_FILE


def base_network_path() -> Path:
    return project_root() / BASE_NETWORK_FILE
