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
