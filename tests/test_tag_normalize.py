"""Tags have one canonical form (lowercase kebab-case) on save, read and search."""
from __future__ import annotations

from forger.models import AnalysisResult, Bookmark
from forger.search import search_bookmarks
from forger.similarity import find_similar_bookmarks
from forger.tagging import clean_tags, normalize_tag, normalize_tags


def test_variants_collapse_to_kebab_case():
    for raw in ["machine learning", "Machine-Learning", "machine_learning",
                "#machine learning", "  machine   learning ", "machine--learning"]:
        assert normalize_tag(raw) == "machine-learning"


def test_existing_canonical_and_symbol_tags_unchanged():
    for tag in ["llm", "ai-tools", "multi-agent", "c++", "node.js"]:
        assert normalize_tag(tag) == tag


def test_normalize_tags_dedupes_and_drops_empty():
    assert normalize_tags(["machine learning", "machine-learning", "", "  ", "LLM"]) == [
        "machine-learning", "llm"]


def test_clean_tags_on_save_is_canonical():
    assert clean_tags(["Machine Learning", "machine-learning", "general"]) == ["machine-learning"]


def test_legacy_bookmark_read_is_canonical_without_rewrite():
    payload = {"id": "b1", "url": "https://x", "tags": ["machine learning", "Machine-Learning"]}
    b = Bookmark.from_dict(payload)
    assert b.tags == ["machine-learning"]
    assert payload["tags"] == ["machine learning", "Machine-Learning"]  # input untouched


def test_legacy_analysis_read_is_canonical():
    a = AnalysisResult.from_dict({"bookmark_id": "b1", "tags": ["Deep_Learning"]})
    assert a.tags == ["deep-learning"]


def test_tag_filter_matches_across_spellings():
    old = Bookmark.from_dict({"id": "a", "url": "u1", "title": "x", "tags": ["machine learning"]})
    new = Bookmark.from_dict({"id": "b", "url": "u2", "title": "y", "tags": ["machine-learning"]})
    hits = [b for b in (old, new) if normalize_tag("Machine Learning") in b.tags]
    assert {b.id for b in hits} == {"a", "b"}


def test_search_finds_both_spellings():
    old = Bookmark.from_dict({"id": "a", "url": "u1", "title": "x", "tags": ["machine learning"]})
    new = Bookmark.from_dict({"id": "b", "url": "u2", "title": "y", "tags": ["machine-learning"]})
    for q in ("machine-learning", "machine learning"):
        ids = {r[1].id for r in search_bookmarks(q, [old, new], {})}
        assert ids == {"a", "b"}


def test_similarity_tag_overlap_ignores_spelling():
    body = "A long usable article body about training neural networks. " * 10
    existing = [{"id": "a", "url": "u", "source": "article", "title": "zzz",
                 "text": body, "tags": ["machine learning"]}]
    hits = find_similar_bookmarks("qqq", ["machine-learning"], "unrelated", existing, threshold=0.3)
    assert hits and any("tag overlap" in str(h) for h in hits)
