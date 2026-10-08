"""Bookmark identity must keep meaningful query strings."""
from forger.bookmark_workflow import check_duplicate
from forger.models import Bookmark
from forger.utils import _canonical_bookmark_identity, stable_bookmark_id


def test_youtube_watch_urls_do_not_collide_and_utm_is_ignored():
    first = "https://www.youtube.com/watch?v=aaa111"
    second = "https://www.youtube.com/watch?v=bbb222"
    tracked = "https://www.youtube.com/watch?v=aaa111&utm_source=twitter&utm_medium=social"

    assert stable_bookmark_id(first, "one") != stable_bookmark_id(second, "two")
    assert stable_bookmark_id(first, "one") == stable_bookmark_id(tracked, "different text")
    assert "utm_source" not in _canonical_bookmark_identity(tracked, "")
    assert "v=aaa111" in _canonical_bookmark_identity(tracked, "")


def test_hacker_news_item_ids_do_not_collide():
    one = stable_bookmark_id("https://news.ycombinator.com/item?id=1", "a")
    two = stable_bookmark_id("https://news.ycombinator.com/item?id=2", "b")
    assert one != two


def test_query_order_and_fragment_do_not_change_id():
    left = "https://example.com/docs?b=2&a=1#section"
    right = "https://example.com/docs?a=1&b=2"
    assert stable_bookmark_id(left, "") == stable_bookmark_id(right, "")
    assert "#" not in _canonical_bookmark_identity(left, "")


def test_x_status_identity_is_preserved():
    x_url = "https://x.com/someone/status/12345?s=20"
    twitter_url = "https://twitter.com/someone/status/12345"
    assert _canonical_bookmark_identity(x_url, "text") == "x-status:12345"
    assert stable_bookmark_id(x_url, "a") == stable_bookmark_id(twitter_url, "b")


def test_second_youtube_video_is_not_a_duplicate(monkeypatch):
    first_url = "https://www.youtube.com/watch?v=aaa111"
    second_url = "https://www.youtube.com/watch?v=bbb222"
    tracked = "https://www.youtube.com/watch?v=aaa111&fbclid=tracking-token"
    existing = Bookmark(
        id=stable_bookmark_id(first_url, "saved text"),
        source="article",
        url=first_url,
        text="saved text",
        title="First video",
    )

    monkeypatch.setattr(
        "forger.bookmark_workflow.load_bookmarks",
        lambda: [existing],
    )

    assert check_duplicate(second_url) is None
    assert check_duplicate(tracked) is existing
