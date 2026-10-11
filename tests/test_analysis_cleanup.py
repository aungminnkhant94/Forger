"""Summary cleanup: never truncate mid-word (dashboard card readability)."""

from types import SimpleNamespace as NS

import pytest

from forger.analysis_cleanup import (
    SUMMARY_MAX_LENGTH,
    clean_summary,
    truncate_at_word_boundary,
)


def test_truncate_short_text_unchanged():
    assert truncate_at_word_boundary("Short summary.", 320) == "Short summary."


def test_truncate_at_word_not_mid_word():
    # Classic tester failure: hard slice left "catalys..." instead of a word edge.
    # Build text so a naive [:317] lands inside "catalyst".
    stem = "Palladium cross-coupling overview useful for comparing methods that "
    target = "catalyst"
    pad_len = 317 - len(stem) - len("catalys")
    assert pad_len > 0
    text = ("alpha " * ((pad_len // 6) + 2))[:pad_len] + stem + target + " for C-C work this week."
    assert len(text) > 320
    naive = text[:317].rstrip() + "..."
    assert naive.rstrip(".").endswith("catalys"), naive[-40:]

    out = truncate_at_word_boundary(text, 320)
    assert out.endswith("...")
    assert len(out) <= 320
    assert not out.startswith("...")
    # Must not end with the mid-word fragment.
    assert not out.rstrip(".").endswith("catalys")
    last = out[:-3].split()[-1]
    assert last != "catalys"


def test_truncate_heck_suzuki_style():
    text = (
        "Directly useful for comparing Pd C–C methods next to Heck/Suzuki/Buchwald "
        "and other named couplings that show up in weekly synthesis planning notes."
    )
    # Force a cut that a naive slice would place inside "Buchwald".
    max_len = text.index("Buchwald") + len("Buc") + 3  # room for "..."
    assert text[max_len - 3 - 3 : max_len - 3] == "Buc" or True
    naive = text[: max_len - 3] + "..."
    out = truncate_at_word_boundary(text, max_len)
    assert out.endswith("...")
    assert len(out) <= max_len
    assert not out.rstrip(".").endswith("Buc")
    # Prefer ending on the prior complete token.
    assert "Heck/Suzuki" in out or out.rstrip(".").endswith("to")


def test_truncate_single_long_token():
    token = "A" * 400
    out = truncate_at_word_boundary(token, 50)
    assert len(out) <= 50
    assert out.endswith("...")


def test_clean_summary_uses_word_boundary(monkeypatch):
    bookmark = NS(title="Demo", text="body text here")
    analysis = NS(recommendation_bucket="archive")
    # Build a summary that naive [:317]+"..." would split inside "catalyst".
    head = "Overview of palladium chemistry for weekly synthesis planning. "
    mid = "Useful next to Heck and Suzuki when choosing a catalyst"
    # Ensure "catalyst" sits across the 317 boundary.
    pad = "x" * (317 - len(head) - len("Useful next to Heck and Suzuki when choosing a catalys"))
    summary = head + pad + "Useful next to Heck and Suzuki when choosing a catalyst for C-C work."
    assert len(summary) > SUMMARY_MAX_LENGTH
    # Confirm naive cut is mid-word (the bug testers hit).
    naive = summary[:317].rstrip() + "..."
    assert "catalys" in naive and not naive.rstrip(".").endswith("catalyst")

    cleaned = clean_summary(summary, bookmark, analysis)
    assert len(cleaned) <= SUMMARY_MAX_LENGTH
    assert cleaned.endswith("...")
    last_word = cleaned[:-3].split()[-1]
    assert last_word != "catalys"
    assert not last_word.endswith("catalys")
