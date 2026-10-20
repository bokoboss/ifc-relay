"""Which PTV Vissim installation the COM build talks to.

Vissim registers one versioned COM ProgID per installed release
(``Vissim.Vissim.2025``, ``Vissim.Vissim.2026`` ...) plus the version-independent
``Vissim.Vissim`` for the most recently registered one. ProgIDs are case-insensitive.

Order: ``VBB_VISSIM_PROGID`` (explicit choice) -> newest supported release that is
registered -> version-independent ProgID.
"""
from __future__ import annotations

import os
import sys

SUPPORTED_RELEASES = (2026, 2025)          # newest first
TESTED_RELEASES = (2025,)                   # built + reopened + checked by an engineer
VERSION_INDEPENDENT = "Vissim.Vissim"


def _registered(prog_id: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id):
            return True
    except OSError:
        return False


def registered_releases() -> list[int]:
    return [r for r in SUPPORTED_RELEASES if _registered(f"Vissim.Vissim.{r}")]


def resolve_prog_id() -> tuple[str | None, str]:
    """(prog_id, how) - prog_id is None when no Vissim COM server is registered."""
    explicit = os.environ.get("VBB_VISSIM_PROGID", "").strip()
    if explicit:
        return explicit, "VBB_VISSIM_PROGID"
    for release in registered_releases():
        return f"Vissim.Vissim.{release}", f"newest registered release ({release})"
    if _registered(VERSION_INDEPENDENT):
        return VERSION_INDEPENDENT, "version-independent ProgID"
    return None, "no Vissim COM server registered"


def release_of(prog_id: str | None) -> int | None:
    if not prog_id:
        return None
    tail = prog_id.rsplit(".", 1)[-1]
    return int(tail) if tail.isdigit() else None


def describe() -> dict[str, object]:
    prog_id, how = resolve_prog_id()
    release = release_of(prog_id)
    return {
        "vissim_prog_id": prog_id,
        "vissim_selection": how,
        "vissim_release": release,
        "vissim_registered_releases": registered_releases(),
        "vissim_release_tested": release in TESTED_RELEASES if release else None,
    }
