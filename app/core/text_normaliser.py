"""
Normalise Russian vehicle registration numbers.
Converts Latin homoglyphs to Cyrillic per ГОСТ Р 50577-2018.
Apply at ingest boundary — before any downstream processing.

Legal plate letters (12): А В Е К М Н О Р С Т У Х
Each has a Latin lookalike that operators type by mistake.
normalise_plate() uppercases first, so only upper→upper mappings are needed.
"""
import re

# 12 Latin uppercase → 12 Cyrillic uppercase, one-to-one
_PLATE_CONFUSABLES = str.maketrans(
    "ABCEHKMOPTXY",   # Latin lookalikes (12)
    "АВСЕНКМОРТХУ",   # Cyrillic equivalents (12)
)

# Matches plate-shaped tokens in free text — letter + 3 digits + 2 letters + 2-3 digits
# Intentionally broad (allows mixed Latin/Cyrillic) so normalise_plate can clean them up.
_PLATE_RE = re.compile(r'\b[А-ЯA-Zа-яa-z]\d{3}[А-ЯA-Zа-яa-z]{2}\d{2,3}\b')


def normalise_plate(raw: str) -> str:
    """Uppercase, resolve Latin homoglyphs, strip separators. Idempotent."""
    if not raw:
        return raw
    return (
        raw.strip()
           .upper()
           .translate(_PLATE_CONFUSABLES)
           .replace(" ", "")
           .replace("-", "")
           .replace(".", "")
    )


def normalise_text_preserving_plates(text: str) -> str:
    """Apply normalise_plate only to plate-shaped tokens in free text."""
    return _PLATE_RE.sub(lambda m: normalise_plate(m.group()), text)
