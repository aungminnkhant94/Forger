"""Search matches simple word forms; no-result suggestions come from related own tags."""
from __future__ import annotations

import argparse
from unittest.mock import patch

import forge
from forger.models import Bookmark
from forger.search import search_bookmarks


def _bm(i, title, text, tags):
    return Bookmark.from_dict({"id": f"bookmark_{i:012d}", "url": f"https://e.com/{i}", "title": title,
                               "text": text, "source": "article", "bookmarked_at": "2026-10-12T00:00:00Z", "tags": tags})


BMS = [
    _bm(1, "Smart Bidding guide", "Google Ads bids rise when you set a target CPA.", ["google-ads", "ppc"]),
    _bm(2, "Sourdough", "How to bake bread at home.", ["bread", "baking"]),
]


def test_bidding_matches_bids():
    hits = search_bookmarks("google ads bidding", BMS, {})
    assert [h[1].id for h in hits] == ["bookmark_000000000001"]


def test_agencies_matches_agency():
    b = [_bm(3, "Agency pricing", "An agency charges retainers.", [])]
    assert search_bookmarks("agencies", b, {})


def test_unrelated_words_still_do_not_match():
    assert search_bookmarks("quantum bidding", BMS, {}) == []


def _search(q, capsys):
    with patch.object(forge, "load_bookmarks", return_value=BMS), \
            patch.object(forge, "load_analysis_results", return_value=[]):
        forge.cmd_search(argparse.Namespace(query=q))
    return capsys.readouterr().out


def test_no_results_suggests_only_related_tags(capsys):
    out = _search("google analytics funnels", capsys)
    assert "No results" in out
    assert "google-ads" in out
    assert "bread" not in out


def test_no_results_without_related_tags_suggests_nothing(capsys):
    out = _search("quantum chromodynamics", capsys)
    assert "bread" not in out and "Related tags" not in out
