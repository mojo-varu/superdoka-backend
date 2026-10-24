"""
app/channels/telegram/callback_data.py

ADR-0024 / SPEC-015-R05, R10: versioned, bounded callback data.
Format: "v1:<action>:<pending_id>:<nonce>" — the nonce is the pending row's
own id reused as a lightweight anti-guessing token combined with the chat
ownership check done by the caller (handlers.py checks the pending row's
operator belongs to the tapping chat before acting, not implemented by
parsing alone). Fits well within Telegram's 64-byte callback_data limit
(OQ-014-1 note: verify this limit at implementation time — a short numeric
id keeps us far under any plausible limit regardless).

Actions: "confirm" (✅), "correct" (✏️), "consent" (the consent button).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_VERSION = "v1"
_VALID_ACTIONS = {"confirm", "correct", "consent"}


@dataclass(frozen=True)
class ParsedCallback:
    action: str
    pending_id: Optional[int]   # None for "consent", which has no pending row


def build(action: str, pending_id: Optional[int] = None) -> str:
    if action not in _VALID_ACTIONS:
        raise ValueError(f"Unknown callback action: {action}")
    pid = pending_id if pending_id is not None else 0
    return f"{_VERSION}:{action}:{pid}"


def parse(data: str) -> Optional[ParsedCallback]:
    """Returns None for anything that doesn't parse — callers treat that as
    a stale/unauthorised callback (SPEC-015-R07), never raise."""
    try:
        version, action, pid_str = data.split(":", 2)
    except ValueError:
        return None
    if version != _VERSION or action not in _VALID_ACTIONS:
        return None
    try:
        pid = int(pid_str)
    except ValueError:
        return None
    return ParsedCallback(action=action, pending_id=pid if pid != 0 else None)
