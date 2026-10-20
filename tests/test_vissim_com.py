"""Vissim release selection (2026 / 2025) and Windows script hygiene."""
from __future__ import annotations

from pathlib import Path

import vissim_com

ROOT = Path(__file__).resolve().parent.parent


def _fake(monkeypatch, registered: set[str]):
    monkeypatch.setattr(vissim_com, "_registered", lambda prog_id: prog_id in registered)
    monkeypatch.delenv("VBB_VISSIM_PROGID", raising=False)


def test_newest_registered_release_wins(monkeypatch):
    _fake(monkeypatch, {"Vissim.Vissim.2025", "Vissim.Vissim.2026", "Vissim.Vissim"})
    assert vissim_com.resolve_prog_id()[0] == "Vissim.Vissim.2026"
    info = vissim_com.describe()
    assert info["vissim_release"] == 2026 and info["vissim_release_tested"] is False


def test_2025_only_and_fallbacks(monkeypatch):
    _fake(monkeypatch, {"Vissim.Vissim.2025"})
    assert vissim_com.resolve_prog_id()[0] == "Vissim.Vissim.2025"
    assert vissim_com.describe()["vissim_release_tested"] is True
    _fake(monkeypatch, {"Vissim.Vissim"})
    assert vissim_com.resolve_prog_id()[0] == "Vissim.Vissim"
    _fake(monkeypatch, set())
    assert vissim_com.resolve_prog_id()[0] is None


def test_explicit_prog_id(monkeypatch):
    _fake(monkeypatch, {"Vissim.Vissim.2026"})
    monkeypatch.setenv("VBB_VISSIM_PROGID", "Vissim.Vissim.2025")
    assert vissim_com.resolve_prog_id() == ("Vissim.Vissim.2025", "VBB_VISSIM_PROGID")


def test_windows_scripts_are_ascii_crlf():
    for path in list(ROOT.glob("*.bat")) + list((ROOT / "scripts").glob("*.ps1")):
        data = path.read_bytes()
        data.decode("ascii")
        assert b"\n" not in data.replace(b"\r\n", b""), f"{path.name} has LF-only line endings"
