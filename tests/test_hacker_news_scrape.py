"""HN item pages via Firebase API (HTML often 419)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from forger.scrape_result import RefuseReason, Saved, scrape_url
from forger.scrapers import article_scraper, hacker_news
from forger.scrapers.hacker_news import (
    is_hn_item_url,
    parse_hn_item_id,
    scrape_hn_item,
)

FIX = Path(__file__).parent / "fixtures" / "hacker_news"


def _json(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_parse_hn_item_id():
    assert parse_hn_item_id("https://news.ycombinator.com/item?id=1") == 1
    assert parse_hn_item_id("https://news.ycombinator.com/item?id=41908121") == 41908121
    assert parse_hn_item_id("https://news.ycombinator.com/") is None
    assert parse_hn_item_id("https://example.com/item?id=1") is None
    assert is_hn_item_url("https://news.ycombinator.com/item?id=1")
    assert not is_hn_item_url("https://news.ycombinator.com/newest")


def _firebase_router(routes: dict[int, dict]):
    def fake_get(url, headers=None, timeout=None):
        for item_id, payload in routes.items():
            if f"/item/{item_id}.json" in url:
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.return_value = payload
                return resp
        raise requests.exceptions.HTTPError("404")

    return fake_get


def test_ask_hn_text_story_via_firebase(monkeypatch):
    ask = _json("item_ask_hn.json")
    monkeypatch.setattr(hacker_news, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(hacker_news.requests, "get", _firebase_router({ask["id"]: ask}))

    result = scrape_hn_item(f"https://news.ycombinator.com/item?id={ask['id']}")
    assert result["success"] is True
    assert "most useful thing AI" in (result["title"] or "")
    assert "running toilet" in (result["text"] or "")
    assert result["source"] == "hn-firebase"
    assert len(result["text"]) > 200


def test_comment_includes_parent_story_title(monkeypatch):
    comment = _json("item_comment.json")
    parent = _json("item_comment_parent.json")
    monkeypatch.setattr(hacker_news, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(
        hacker_news.requests,
        "get",
        _firebase_router({comment["id"]: comment, parent["id"]: parent}),
    )

    result = scrape_hn_item(f"https://news.ycombinator.com/item?id={comment['id']}")
    assert result["success"] is True
    assert "documentary" in (result["title"] or "").lower()
    assert "Ben Ferencz" in (result["text"] or "") or "Nuremburg" in (result["text"] or "")
    assert result["source"] == "hn-firebase"


def test_story_with_url_follows_outbound_article(monkeypatch):
    story = _json("item_1_story.json")
    monkeypatch.setattr(hacker_news, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(hacker_news.requests, "get", _firebase_router({1: story}))

    article_body = (
        "Y Combinator is a startup accelerator based in Silicon Valley. "
        "It funds early-stage companies and runs a three-month program "
        "that ends with Demo Day. Many notable tech companies started there. "
        "This paragraph pads the extract past the usable-text threshold."
    )

    def fake_article(url, timeout=15):
        assert "ycombinator.com" in url
        return {
            "success": True,
            "title": "Y Combinator Home",
            "text": article_body,
            "author": None,
            "source": "requests+bs4",
            "error": None,
        }

    monkeypatch.setattr(article_scraper, "scrape_article", fake_article)
    result = scrape_hn_item("https://news.ycombinator.com/item?id=1")
    assert result["success"] is True
    assert result["title"] == "Y Combinator"  # HN title preferred
    assert "startup accelerator" in result["text"]
    assert result["source"].startswith("hn-firebase+")


def test_scrape_url_hn_item_does_not_hit_html_419(monkeypatch):
    ask = _json("item_ask_hn.json")
    monkeypatch.setattr(hacker_news, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(article_scraper, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(hacker_news.requests, "get", _firebase_router({ask["id"]: ask}))

    def boom(*a, **k):
        raise requests.exceptions.HTTPError("419 Client Error")

    monkeypatch.setattr(article_scraper, "_fetch_url", boom)

    out = scrape_url(f"https://news.ycombinator.com/item?id={ask['id']}")
    assert isinstance(out, Saved)
    assert "most useful thing AI" in out.title
