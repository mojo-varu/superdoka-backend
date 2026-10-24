"""
tests/channels/test_callback_data_and_delivery.py

AC-015-10 (callback format) and AC-014-08 (message splitting) — both pure
functions, CONFIRMED-RUN in this sandbox (see runner at bottom + report).
"""
from __future__ import annotations

from app.channels.telegram import callback_data
from app.channels.telegram.delivery import MESSAGE_LIMIT, split_text


def test_callback_build_and_parse_roundtrip():
    data = callback_data.build("confirm", 42)
    assert data == "v1:confirm:42"
    parsed = callback_data.parse(data)
    assert parsed is not None
    assert parsed.action == "confirm"
    assert parsed.pending_id == 42


def test_callback_parse_rejects_garbage():
    assert callback_data.parse("not-a-callback") is None
    assert callback_data.parse("v1:unknown_action:1") is None
    assert callback_data.parse("v2:confirm:1") is None   # wrong version
    assert callback_data.parse("v1:confirm:not_a_number") is None


def test_callback_consent_has_no_pending_id():
    data = callback_data.build("consent")
    parsed = callback_data.parse(data)
    assert parsed.action == "consent"
    assert parsed.pending_id is None


def test_split_text_under_limit_is_unchanged():
    text = "короткий ответ"
    assert split_text(text) == [text]


def test_split_text_splits_at_paragraph_boundary():
    para_a = "A" * (MESSAGE_LIMIT - 10)
    para_b = "B" * 500
    text = f"{para_a}\n\n{para_b}"
    chunks = split_text(text)
    assert len(chunks) == 2
    assert all(len(c) <= MESSAGE_LIMIT for c in chunks)
    assert chunks[0] == para_a
    assert chunks[1] == para_b


def test_split_text_hard_slices_a_single_oversized_paragraph():
    huge = "X" * (MESSAGE_LIMIT * 2 + 100)
    chunks = split_text(huge)
    assert all(len(c) <= MESSAGE_LIMIT for c in chunks)
    assert "".join(chunks) == huge


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
