"""Where the app finds the external Geometry Engine and Vissim base network.

The engine (05_geometry_engine_v03.py) and base_empty.inpx are not part of the
repository. Lookup order:

1. ``VBB_PROJECT_ROOT`` environment variable, if set.
2. ``<app>/local`` if it contains the engine (layout created by install.bat).
3. The parent folder of the app if it contains the engine (original layout).
4. ``<app>/local`` (default for a fresh install; files can be added later).
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ENGINE_FILE = "05_geometry_engine_v03.py"
BASE_NETWORK_FILE = "base_empty.inpx"


def project_root() -> Path:
    env = os.environ.get("VBB_PROJECT_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    local = APP_DIR / "local"
    if (local / ENGINE_FILE).exists():
        return local
    if (APP_DIR.parent / ENGINE_FILE).exists():
        return APP_DIR.parent
    return local
