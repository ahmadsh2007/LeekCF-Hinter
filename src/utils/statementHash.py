import hashlib
import re
import unicodedata

ZERO_WIDTH_CHARS = re.compile(r"[​‌‍⁠﻿]")
WHITESPACE_RUNS = re.compile(r"\s+")

# Notes and sample tests are deliberately left out: they explain the samples but do not change the problem.
HASHED_TEXT_FIELDS = (
    "statement_text",
    "input_specification",
    "output_specification",
    "interaction_specification",
)

def normalizeText(text: str) -> str:
    """Removes formatting drift (odd spaces, zero-width characters, line breaks) but keeps case and LaTeX."""
    text = unicodedata.normalize("NFKC", text)
    text = ZERO_WIDTH_CHARS.sub("", text)
    return WHITESPACE_RUNS.sub(" ", text).strip()

def computeStatementHash(specs: dict) -> str:
    """
    Fingerprint of a problem for duplicate detection. Covers the limits too, so a variant with
    different limits (whose hints could differ) is not silently merged with the original.
    Fields are labelled so the same text as an Output section and as an Interaction section differs.
    """
    parts = [
        f"time_limit_ms={specs['time_limit_ms']}",
        f"memory_limit_mb={specs['memory_limit_mb']}",
    ]
    for field in HASHED_TEXT_FIELDS:
        parts.append(f"{field}={normalizeText(specs.get(field) or '')}")

    # \x1f cannot survive normalizeText (it counts as whitespace), so it is a safe separator.
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
