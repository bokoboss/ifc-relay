"""The browser UI script, read as one text for contract tests.

app.js is split into classic scripts that share globals; index.html loads them
in this order, so their concatenation is what the browser runs."""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP_JS_FILES = ("app.js", "app-plan.js", "app-model.js", "app-review.js", "app-tree.js", "app-build.js")


def app_js() -> str:
    return "\n".join((STATIC / name).read_text(encoding="utf-8") for name in APP_JS_FILES)
