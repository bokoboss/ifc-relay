import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

# Run geometry extraction inside the test process (no worker pool to outlive pytest).
os.environ.setdefault("VBB_GEOMETRY_IN_PROCESS", "1")
os.environ.setdefault("VBB_PERF_LOG", "")          # no performance log from tests
