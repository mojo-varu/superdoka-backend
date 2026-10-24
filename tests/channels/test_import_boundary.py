"""
tests/channels/test_import_boundary.py

SPEC-014-R13 / AC-014-11 / ADR-0020: a static check — the ENGINE
(app/core, app/services, app/db, app/rules) must never import app/channels
or aiogram, and app/channels must import only app/channels/base.py and the
engine's single entry point (app/services/engine_entrypoint.handle_inbound)
from the engine side.

Pure AST parsing — no aiogram, no DB, no network. This is one of the few
tests in this phase I could actually execute in this sandbox (no
dependencies needed beyond the stdlib); see CONFIRMED-RUN markers below and
the final report for which others are author-only.

CONFIRMED-RUN: this file was executed directly with `python3` (not pytest,
which isn't installed in this sandbox) via a small runner at the bottom —
see the final report for the exact command and its output.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIRS = ["app/core", "app/services", "app/db", "app/rules"]
CHANNEL_DIR = "app/channels"

ALLOWED_CHANNEL_TO_ENGINE_IMPORTS = {
    "app.channels.base",
    "app.services.engine_entrypoint",   # the single entry point, handle_inbound
    "app.schemas.channel",              # the contract's real home; app/channels/base.py re-exports it
}


def _iter_py_files(rel_dir: str):
    base = REPO_ROOT / rel_dir
    if not base.exists():
        return
    for path in base.rglob("*.py"):
        yield path


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def test_engine_never_imports_channels_or_aiogram():
    violations = []
    for rel_dir in ENGINE_DIRS:
        for path in _iter_py_files(rel_dir):
            for mod in _imported_modules(path):
                if mod.startswith("app.channels") or mod == "aiogram" or mod.startswith("aiogram."):
                    violations.append(f"{path.relative_to(REPO_ROOT)} imports {mod}")
    assert not violations, "Engine code imports the channel layer or aiogram:\n" + "\n".join(violations)


def test_channels_only_import_base_and_handle_inbound_from_engine():
    engine_prefixes = ("app.core", "app.services", "app.db", "app.rules", "app.schemas", "app.api")
    violations = []
    for path in _iter_py_files(CHANNEL_DIR):
        for mod in _imported_modules(path):
            if not mod.startswith(engine_prefixes):
                continue
            if mod in ALLOWED_CHANNEL_TO_ENGINE_IMPORTS:
                continue
            violations.append(f"{path.relative_to(REPO_ROOT)} imports {mod}")
    assert not violations, (
        "app/channels imports engine modules other than base.py / "
        "engine_entrypoint.handle_inbound:\n" + "\n".join(violations)
        + "\n\nNOTE: this assertion is currently known to FAIL — see the "
        "final report. app/channels/worker.py, webhook.py and polling.py "
        "import app.db.database/app.db.models directly for the "
        "insert_received_row/recovery-sweep logic (the 'acknowledge fast' "
        "half of WP-C), which ADR-0020 as literally written has no "
        "sanctioned second entry point for. This is a real, reported gap, "
        "not a passing test — see the report for the proposed resolution "
        "(either a narrow ADR-0020 amendment for the intake helper, or "
        "moving insert_received_row behind its own tiny engine function)."
    )


if __name__ == "__main__":
    # Minimal runner — no pytest available in this sandbox (see report).
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)
