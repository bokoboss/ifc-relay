from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ProjectStateStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": "0.3",
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
        self.path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def reset(self) -> None:
        if self.path.exists():
            self.path.unlink()
