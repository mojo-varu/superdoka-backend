"""
tests/channels/test_delivery_resilience.py

Test scenario 9 (retry_after retried within cap) and 10 ("blocked by user"
marks unreachable without crashing) from the build prompt's list. CONFIRMED-
RUN: _send_one_with_retry is duck-typed against bot_send_fn specifically so
it can be tested with a plain async fake, no real aiogram Bot (see
delivery.py's docstring). asyncio.run is used directly (no pytest-asyncio
installed in this sandbox).
"""
from __future__ import annotations

import asyncio

from app.channels.telegram.delivery import RETRY_CAP, UserUnreachable, _send_one_with_retry


class _RetryAfterError(Exception):
    def __init__(self, retry_after: float):
        super().__init__("Flood control exceeded")
        self.retry_after = retry_after


class _BlockedError(Exception):
    def __init__(self):
        super().__init__("Forbidden: bot was blocked by the user")


def test_retry_after_is_retried_then_succeeds():
    attempts = []

    async def flaky_send(chat_id, text, reply_markup=None):
        attempts.append(1)
        if len(attempts) < 2:
            raise _RetryAfterError(retry_after=0.01)
        return None   # success on 2nd attempt

    asyncio.run(_send_one_with_retry(flaky_send, "123", "hello", None))
    assert len(attempts) == 2


def test_retry_after_gives_up_cleanly_at_cap():
    attempts = []

    async def always_rate_limited(chat_id, text, reply_markup=None):
        attempts.append(1)
        raise _RetryAfterError(retry_after=0.01)

    # Must not raise — WP-F: drop the message rather than block the worker.
    asyncio.run(_send_one_with_retry(always_rate_limited, "123", "hello", None))
    assert len(attempts) == RETRY_CAP


def test_blocked_by_user_raises_user_unreachable_without_crashing_worker():
    async def blocked_send(chat_id, text, reply_markup=None):
        raise _BlockedError()

    raised = False
    try:
        asyncio.run(_send_one_with_retry(blocked_send, "123", "hello", None))
    except UserUnreachable:
        raised = True
    assert raised, "a 'blocked by user' error must surface as UserUnreachable, not propagate raw"


if __name__ == "__main__":
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
