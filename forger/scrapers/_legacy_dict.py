"""Legacy scrape dict shape for unpeeled callers.

Adapters that already return :class:`~forger.scrape_result.ScrapeOutcome`
convert here when an old ``scrape_article``-style dict is still required.
New ``"success"`` dict literals belong in this module only; leftover inline
dicts in other scrapers are frozen by ``tests/test_no_new_success_dicts.py``.
"""
from __future__ import annotations

from forger.scrape_result import Refused, Saved, ScrapeOutcome


def outcome_to_legacy_dict(outcome: ScrapeOutcome) -> dict:
    """Convert Saved|Refused to the historical scraper dict."""
    if isinstance(outcome, Saved):
        return {
            "success": True,
            "title": outcome.title,
            "text": outcome.text,
            "author": outcome.author,
            "source": outcome.via,
            "error": None,
        }
    assert isinstance(outcome, Refused)
    return {
        "success": False,
        "title": None,
        "text": None,
        "author": None,
        "source": None,
        "error": outcome.detail or outcome.reason.value,
    }
