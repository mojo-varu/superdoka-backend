"""
app/channels/

The Telegram (and future MAX) bot runtime. This package is an interface layer
on top of the engine (app/core, app/services, app/db, app/rules) — see
ADR-0020. It is one-directional: code in here may import app/channels/base.py
and the engine's single entry point (app/services/engine_entrypoint.handle_inbound),
and nothing else from the engine side. The engine must never import this
package or aiogram (SPEC-014-R13, enforced by tests/channels/test_import_boundary.py).
"""
