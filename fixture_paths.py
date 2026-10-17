"""Locations of regression fixtures that are not committed to the repository.

Project BIM files must stay outside the public repo, so regression scripts look
for them via environment variables (and then fall back to globbing the parent
project folder) instead of hard-coding project file names.

    VBB_LARGE_IFC   path to the large structural IFC used by checks 41/43/45/46
"""

from __future__ import annotations

import os
from pathlib import Path


def large_ifc_from_env() -> Path | None:
    value = os.environ.get("VBB_LARGE_IFC", "").strip()
    return Path(value) if value else None
