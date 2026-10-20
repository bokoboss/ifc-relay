from pathlib import Path

from vissim_build_service import build_failure_message


def test_traceback_survives_long_validation_output():
    stdout = "\n".join(f"- {{'type': 'obstacle_overlap', 'objects': [{i}, {i + 1}]}}" for i in range(5000))
    stdout += "\nConnecting to Vissim 2025..."
    stderr = "Traceback (most recent call last):\n  ...\npywintypes.com_error: (-2147221005, 'Invalid class string', None, None)"
    msg = build_failure_message(1, Path("x/build.log"), stdout, stderr)
    assert "Invalid class string" in msg
    assert msg.rstrip().endswith("None, None)")
    assert "Connecting to Vissim 2025..." in msg
    assert len(msg) < 9000


def test_com_server_execution_failure_gets_thai_hint():
    stderr = "pywintypes.com_error: (-2146959355, 'Server execution failed', None, None)"
    msg = build_failure_message(1, Path("b.log"), "Connecting to Vissim 2025...", stderr)
    assert msg.startswith("Vissim เปิดขึ้นมาแต่ไม่ตอบการเชื่อมต่อ")
    assert "Server execution failed" in msg


def test_preflight_reports_missing_base_network(tmp_path):
    from vissim_build_service import build_preflight
    problems = build_preflight(tmp_path / "local" / "base_empty.inpx")
    assert len(problems) == 1 and "base_empty.inpx" in problems[0] and "File > New" in problems[0]
    (tmp_path / "base.inpx").write_text("<network/>")
    assert build_preflight(tmp_path / "base.inpx") == []


def test_import_accepts_ifc_only():
    from fastapi.testclient import TestClient

    import app as app_module
    client = TestClient(app_module.app)
    r = client.post("/api/import", files={"file": ("plan.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 400
    assert ".ifc" in r.json()["detail"]
