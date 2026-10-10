"""Validate agent-mode ``relates_to`` prose (Relates to you).

Agents must write 2+ sentences grounded in profile.md — never placeholders
like ``None`` / ``N/A``.
"""
from __future__ import annotations

import re

# Minimum length after strip. Short enough for a tight two-sentence note,
# long enough to block "None" / "N/A" / one-word stubs.
RELATES_TO_MIN_CHARS = 40

# Exact whole-string placeholders (case-insensitive) — never meaningful prose.
_PLACEHOLDER_EXACT = frozenset(
    {
        "",
        "-",
        "--",
        "—",
        "none",
        "null",
        "nil",
        "n/a",
        "n.a.",
        "na",
        "nothing",
        "no",
        "nope",
        "unknown",
        "tbd",
        "todo",
        "n/a.",
        "none.",
        "null.",
        "nothing connects",
        "no connection",
        "not applicable",
        "no relation",
        "does not relate",
        "doesn't relate",
    }
)

_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def normalize_relates_to(value: object) -> str:
    """Strip and stringify; treat JSON null-like values as empty."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    text = str(value).strip()
    # Agents sometimes write the literal words None/null as the whole field.
    return text


def is_placeholder_relates_to(value: object) -> bool:
    """True when the value is empty or a known non-prose placeholder."""
    text = normalize_relates_to(value)
    if not text:
        return True
    return text.lower().rstrip(".") in _PLACEHOLDER_EXACT or text.lower() in _PLACEHOLDER_EXACT


def is_meaningful_relates_to(value: object) -> bool:
    """True when ``relates_to`` is real prose suitable for Relates to you.

    Rule:
    - not empty / whitespace
    - not a placeholder (None, N/A, null, -, …)
    - at least ``RELATES_TO_MIN_CHARS`` characters
    - at least two sentence-like segments (split on ``.?!``)
    """
    text = normalize_relates_to(value)
    if is_placeholder_relates_to(text):
        return False
    if len(text) < RELATES_TO_MIN_CHARS:
        return False
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    return len(parts) >= 2


def validate_relates_to(value: object) -> str:
    """Return cleaned prose or raise ``ValueError`` with a clear message."""
    text = normalize_relates_to(value)
    if is_placeholder_relates_to(text):
        raise ValueError(
            "relates_to is required: write 2-4 sentences tying this bookmark to "
            "goals/projects in profile.md (do not use None/N/A/null/-)"
        )
    if len(text) < RELATES_TO_MIN_CHARS:
        raise ValueError(
            f"relates_to is too short ({len(text)} chars): need at least "
            f"{RELATES_TO_MIN_CHARS} characters of prose from profile.md"
        )
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    if len(parts) < 2:
        raise ValueError(
            "relates_to must be at least 2 sentences (end clauses with . ? or !) "
            "naming how this fits the user's profile.md"
        )
    return text
