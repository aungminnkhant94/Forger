"""Python side of the shared text-rule cases.

The same table is checked against web/lib/*.ts by web/scripts/shared-cases.test.mjs,
so the Python and dashboard copies of these rules cannot drift apart.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forger.analysis_cleanup import truncate_at_word_boundary
from forger.search import normalize, query_terms, term_stem
from forger.tagging import normalize_tag

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "shared_cases" / "text_rules.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES["normalize_tag"], ids=lambda c: repr(c["input"]))
def test_normalize_tag(case):
    assert normalize_tag(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["search_query_terms"], ids=lambda c: repr(c["input"]))
def test_search_query_terms(case):
    assert query_terms(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["search_normalize"], ids=lambda c: repr(c["input"]))
def test_search_normalize(case):
    assert normalize(case["input"]) == case["expected"]


@pytest.mark.parametrize(
    "case", CASES["truncate_at_word_boundary"], ids=lambda c: f"{c['input'][:20]!r}@{c['max_length']}"
)
def test_truncate_at_word_boundary(case):
    assert truncate_at_word_boundary(case["input"], case["max_length"], case["ellipsis"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["search_term_stem"], ids=lambda c: repr(c["input"]))
def test_search_term_stem(case):
    assert term_stem(case["input"]) == case["expected"]
