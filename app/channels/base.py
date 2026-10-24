"""
app/channels/base.py

Re-exports the channel-neutral contract from app/schemas/channel.py, which
is where the real definitions now live (see that module's docstring for
why). This keeps "app/channels/* may import only app/channels/base.py from
the engine side" (ADR-0020) true for existing and future channel code,
without the engine having to import anything under app/channels/ to use the
same types.
"""
from __future__ import annotations

from app.schemas.channel import (  # noqa: F401
    ChannelAdapter,
    ChatType,
    InlineButton,
    MediaKind,
    NormalisedInbound,
    OutboundMessage,
)
