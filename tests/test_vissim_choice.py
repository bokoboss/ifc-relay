"""Several Vissim releases installed: the engineer can pick one, and without a
pick the build moves on to the next release when one will not start."""
from __future__ import annotations

import pytest


class FakeEngine:
    def __init__(self, failing):
        self.failing, self.tried, self.PROG_ID = failing, [], None

    def main(self):
        self.tried.append(self.PROG_ID)
        if self.PROG_ID in self.failing:
            raise Exception(-2146959355, "Server execution failed", None, None)


def test_falls_back_to_the_next_release_when_one_will_not_start():
    from vissim_build_adapter import run_with_fallback
    engine = FakeEngine({"Vissim.Vissim.2026"})
    assert run_with_fallback(engine, ["Vissim.Vissim.2026", "Vissim.Vissim.2025"]) == "Vissim.Vissim.2025"
    assert engine.tried == ["Vissim.Vissim.2026", "Vissim.Vissim.2025"]


def test_other_errors_and_last_candidate_are_raised():
    from vissim_build_adapter import run_with_fallback

    class Broken(FakeEngine):
        def main(self):
            self.tried.append(self.PROG_ID)
            raise ValueError("geometry problem")

    engine = Broken(set())
    with pytest.raises(ValueError):
        run_with_fallback(engine, ["Vissim.Vissim.2026", "Vissim.Vissim.2025"])
    assert engine.tried == ["Vissim.Vissim.2026"]                    # not a start-up failure: no retry
    with pytest.raises(Exception, match="Server execution failed"):
        run_with_fallback(FakeEngine({"Vissim.Vissim.2025"}), ["Vissim.Vissim.2025"])


def test_candidates_explicit_choice_is_the_only_one(monkeypatch):
    import vissim_com
    monkeypatch.setattr(vissim_com, "registered_releases", lambda: [2026, 2025])
    monkeypatch.delenv("VBB_VISSIM_PROGID", raising=False)
    assert vissim_com.candidates() == ["Vissim.Vissim.2026", "Vissim.Vissim.2025"]
    monkeypatch.setenv("VBB_VISSIM_PROGID", "Vissim.Vissim.2025")
    assert vissim_com.candidates() == ["Vissim.Vissim.2025"]


def test_failure_message_names_the_vissim_tried(tmp_path):
    from vissim_build_service import build_failure_message
    msg = build_failure_message(1, tmp_path / "b.log",
                                "Vissim COM ProgID: Vissim.Vissim.2026 (attempt 1/1)\nConnecting...",
                                "pywintypes.com_error: (-2146959355, 'Server execution failed', None, None)")
    assert "Vissim ที่ลองเชื่อมต่อ: Vissim.Vissim.2026" in msg


def test_choice_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    import vissim_com
    monkeypatch.setattr(vissim_com, "registered_releases", lambda: [2026, 2025])
    monkeypatch.setattr(app_module, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(app_module, "_LAUNCH_PROGID", "")
    monkeypatch.delenv("VBB_VISSIM_PROGID", raising=False)
    client = TestClient(app_module.app)
    assert client.post("/api/vissim", json={"release": 2024}).status_code == 400
    r = client.post("/api/vissim", json={"release": 2025}).json()
    assert r["choice"] == 2025 and r["vissim_prog_id"] == "Vissim.Vissim.2025"
    r = client.post("/api/vissim", json={"release": None}).json()
    assert r["choice"] is None and "VBB_VISSIM_PROGID" not in __import__("os").environ
