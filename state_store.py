from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from version import PROJECT_STATE_VERSION


class ProjectStateStore:
    """One local project, one operator (F-07).

    Requests run on a thread pool, so every read-modify-write of the state is
    done while holding ``lock`` (re-entrant); long jobs compute without it and
    take it only to re-read and commit their result.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": PROJECT_STATE_VERSION,
                "upload": None,
                "analysis": None,
                "geometry": None,
                "selection": {
                    "mode": "auto",
                    "overrides": {},
                },
                "semantic": None,
                "build": {
                    "status": "not_ready",
                },
            }

        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, state: dict[str, Any]) -> None:
        # Write to a sibling temp file and atomically replace, so an
        # interrupted write never leaves a truncated project_state.json.
        # Unique per write: two threads sharing one temp name could replace the
        # file with the other's half-written content.
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def reset(self) -> None:
        with self.lock:
            if self.path.exists():
                self.path.unlink()
