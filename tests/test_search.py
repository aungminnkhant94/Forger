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


def test_roche_does_not_match_electrochemical():
    """Word-boundary: Roche must not hit electROCHEmical / ElectroChem."""
    electro = [
        bm("jacs", "JACS Au electrochemical DoE", "Design of experiments."),
        bm("acs", "ACS electrochemical CFP", "Call for papers."),
        bm("cec", "ChemElectroChem collection", "Special issue."),
    ]
    roche = bm("roche", "Roche job posting", "Join Roche in Basel, Switzerland.")
    hit_ids = {b.id for _, b, _, _ in search_bookmarks("Roche", electro + [roche], {})}
    assert hit_ids == {"roche"}


def test_stem_still_matches_whole_token_word_forms():
    b = bm("ads", "Smart Bidding", "Google Ads bids rise with target CPA.")
    assert {x.id for _, x, _, _ in search_bookmarks("bidding", [b], {})} == {"ads"}
    assert {x.id for _, x, _, _ in search_bookmarks("bids", [b], {})} == {"ads"}


def test_en_dash_and_other_dashes_search_like_hyphen():
    from forger.search import normalize, query_terms
    for dash in ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212", "\uff0d"]:
        assert query_terms(f"C{dash}H activation") == query_terms("C-H activation")
        assert normalize(f"Late-stage C{dash}H functionalization") == normalize(
            "Late-stage C-H functionalization"
        )


def test_en_dash_query_finds_hyphen_and_en_dash_bookmarks():
    books = [
        bm("hy", title="Pd-catalysed C-H activation"),
        bm("en", title="Directed C\u2013H activation of arenes"),
        bm("no", title="Electrochemical activation of CO2"),
    ]
    ids = lambda q: {b.id for _, b, _, _ in search_bookmarks(q, books, {})}
    assert ids("C\u2013H activation") == {"hy", "en"}
    assert ids("C-H activation") == {"hy", "en"}
