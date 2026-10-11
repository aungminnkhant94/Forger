"""forge search: multi-word AND matching, hyphen/space equivalence."""
from types import SimpleNamespace as NS

import pytest

from forger.search import normalize, query_terms, score_bookmark, search_bookmarks


def bm(id, title="", text="", tags=()):
    return NS(id=id, title=title, text=text, tags=list(tags))


def an(id, summary="", insights=()):
    return NS(bookmark_id=id, summary=summary, key_insights=list(insights))


BOOKMARKS = [
    bm("lig", "Ligand field basics", "How denticity changes chelate stability.", ["coordination"]),
    bm("nist", "NIST Chemistry WebBook", "Thermo data for ethanol and other solvents."),
    bm("sds", "Lab safety refresher", "Always read the SDS before handling.", ["lab-safety"]),
    bm("named", "Organic chemistry cheat sheet", "A list of named reactions.", []),
    bm("namedtag", "Aldol tricks", "Practice set.", ["named-reactions"]),
    bm("heck", "Cross coupling primer", "Palladium chemistry intro."),
    bm("other", "Ethanol fuel economics", "Market report."),
]
ANALYSES = {
    "heck": an("heck", "Overview of Pd catalysis.", ["The Heck reaction couples alkenes."]),
    "other": an("other", "Biofuel prices.", []),
}


def ids(query):
    return {b.id for _, b, _, _ in search_bookmarks(query, BOOKMARKS, ANALYSES)}


@pytest.mark.parametrize(
    "query,expected",
    [
        ("ligand denticity", {"lig"}),
        ("denticity ligand", {"lig"}),            # any order
        ("NIST ethanol", {"nist"}),                # 'other' has ethanol only
        ("lab safety SDS", {"sds"}),
        ("named reactions", {"named", "namedtag"}),
        ("named-reactions", {"named", "namedtag"}),
    ],
)
def test_tester_examples(query, expected):
    assert ids(query) == expected


def test_hyphen_and_space_equivalent():
    assert ids("named reactions") == ids("named-reactions")
    assert ids("lab-safety") == ids("lab safety") >= {"sds"}


def test_single_word_unchanged():
    assert ids("ligand") == {"lig"}
    assert ids("ethanol") == {"nist", "other"}
    # Heck still matches via insights only — not widened to more bookmarks.
    assert ids("heck") == {"heck"}


def test_all_words_required():
    assert ids("ligand ethanol") == set()
    assert ids("NIST benzene") == set()


def test_short_hyphen_group_is_one_term():
    assert query_terms("C-H activation") == ["c h", "activation"]
    assert query_terms("named-reactions") == query_terms("named reactions") == ["named", "reactions"]
    # 'c-h' must not explode into single letters matching everything.
    assert ids("c-h") == set()


def test_title_outranks_body():
    results = search_bookmarks("lab safety", BOOKMARKS, ANALYSES)
    assert results[0][1].id == "sds"
    assert "title" in results[0][3]


def test_empty_query_matches_nothing():
    assert score_bookmark("   ", BOOKMARKS[0]) == (0, [])
    assert normalize("A--B__c/d") == "a b c d"


def test_hyphen_query_matches_scattered_words_like_space_query():
    extra = BOOKMARKS + [bm("scatter", "Reactions of alkenes", "Some are named after chemists.")]
    q = lambda query: {b.id for _, b, _, _ in search_bookmarks(query, extra, ANALYSES)}
    assert q("named-reactions") == q("named reactions") >= {"scatter", "named", "namedtag"}
