"""Bookmark text search shared by `forge search`.

Rules:
- Case-insensitive.
- Hyphens (and en/em dash, minus, non-breaking hyphen etc.), underscores and slashes are treated as spaces, in both query and
  fields, so ``named-reactions`` and ``named reactions`` are equivalent.
- A multi-word query matches a bookmark only when EVERY word appears somewhere
  in the searched fields (any order, may be spread across fields).
- Short hyphen groups with a 1-char piece (``C-H``) stay one phrase term.
- A single-word query matches **whole tokens** only (word boundaries), not
  arbitrary substrings: ``Roche`` matches ``Roche`` / ``roche`` but not
  ``electrochemical`` / ``ElectroChem``.
- Light word forms: a term also matches by its stem (``bidding`` -> ``bid``
  matches "bids"; ``agencies`` -> ``agency``). Stem matches are also
  token-bounded — see term_stem / term_in.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# ASCII hyphen plus Unicode dash variants (hyphen, non-breaking hyphen,
# figure/en/em dash, horizontal bar, minus sign, small/fullwidth hyphen-minus)
# so "C–H" (en dash, common in chemistry titles) searches like "C-H".
_SEPARATORS = re.compile("[-_/\u2010-\u2015\u2212\ufe58\ufe63\uff0d]+")
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")

# (field name, weight) — same fields and weights as the original cmd_search.
FIELD_WEIGHTS = {
    "title": 10,
    "text": 5,
    "tag": 8,
    "summary": 3,
    "insight": 2,
}


def normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return _WHITESPACE.sub(" ", _SEPARATORS.sub(" ", text.lower())).strip()


def query_terms(query: str) -> list[str]:
    """Split the query into required terms.

    Whitespace and ``-``/``_``/``/`` both separate words, so ``named-reactions``
    and ``named reactions`` give the same terms. Exception: a hyphenated word with
    a one-character piece (``C-H``, ``E-Z``) stays one phrase term (``"c h"``) so
    it can't degrade into single letters that match nearly everything.
    """
    terms: list[str] = []
    for part in (query or "").split():
        pieces = normalize(part).split(" ")
        pieces = [p for p in pieces if p]
        if not pieces:
            continue
        if len(pieces) > 1 and any(len(p) < 2 for p in pieces):
            terms.append(" ".join(pieces))
        else:
            terms.extend(pieces)
    return terms


_SUFFIXES = ("ies", "ing", "ers", "er", "ed", "es", "s")


def term_stem(term: str) -> str:
    """Crude stem for matching word forms; phrases and short words unchanged."""
    if " " in term or term.endswith("ss"):
        return term
    for suf in _SUFFIXES:
        if term.endswith(suf) and len(term) - len(suf) >= 3:
            stem = term[: -len(suf)]
            if suf == "ies":
                return stem + "y"
            if len(stem) >= 4 and stem[-1] == stem[-2] and stem[-1] not in "aeiouls":
                stem = stem[:-1]  # bidd -> bid, runn -> run
            return stem
    return term


def term_in(term: str, value: str) -> bool:
    """True if ``term`` matches a whole token in normalized ``value``.

    Phrase terms (space inside, e.g. ``c h``) need consecutive tokens.
    Otherwise the term or its stem must equal a token or that token's stem,
    so ``bidding``↔``bids`` still works but ``roche`` does not hit
    ``electrochemical``.
    """
    if not term or not value:
        return False
    tokens = _TOKEN.findall(value)
    if not tokens:
        return False
    if " " in term:
        parts = term.split()
        n = len(parts)
        for i in range(len(tokens) - n + 1):
            if tokens[i : i + n] == parts:
                return True
        return False
    stem = term_stem(term)
    return any(tok == term or term_stem(tok) == stem for tok in tokens)


def _fields(bookmark, analysis) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = [
        ("title", normalize(" | ".join(filter(None, [
            getattr(bookmark, "title", None),
            getattr(analysis, "title", None) if analysis is not None else None,
        ])))),
        ("text", normalize(getattr(bookmark, "text", None))),
        ("tag", " | ".join(normalize(t) for t in (getattr(bookmark, "tags", None) or []))),
    ]
    if analysis is not None:
        out.append(("summary", normalize(getattr(analysis, "summary", None))))
        out.append((
            "insight",
            " | ".join(normalize(i) for i in (getattr(analysis, "key_insights", None) or [])),
        ))
    return out


def score_bookmark(query: str, bookmark, analysis=None) -> tuple[int, list[str]]:
    """Return (score, matched_field_names). Score 0 means no match."""
    terms = query_terms(query)
    if not terms:
        return 0, []
    phrase = " ".join(terms)
    fields = _fields(bookmark, analysis)

    # Gate: every term must appear in at least one field.
    if not all(any(term_in(t, value) for _, value in fields) for t in terms):
        return 0, []

    score = 0
    matches: list[str] = []
    for name, value in fields:
        if not value:
            continue
        weight = FIELD_WEIGHTS[name]
        if term_in(phrase, value) or (len(terms) == 1 and term_in(terms[0], value)):
            score += weight
            matches.append(name)
        elif len(terms) > 1:
            hit = sum(1 for t in terms if term_in(t, value))
            if hit:
                # Partial credit, proportional to words found in this field.
                score += max(1, weight * hit // (2 * len(terms)))
                matches.append(name)
    return score, matches


def search_bookmarks(query: str, bookmarks: Iterable, analysis_map: dict) -> list:
    """Return [(score, bookmark, analysis, matches)] sorted best-first."""
    results = []
    for b in bookmarks:
        a = analysis_map.get(b.id)
        score, matches = score_bookmark(query, b, a)
        if score > 0:
            results.append((score, b, a, matches))
    results.sort(key=lambda x: -x[0])
    return results
