"""Tags: no junk heuristics before resolve; high-signal rules still work."""
from forger.tagging import clean_tags, infer_tags


def test_infer_tags_no_domain_fallbacks():
    """Bare URLs must not invent research / ai-tools / coding fillers."""
    assert infer_tags("https://example.com/doi/10.1021/abc", "Organic synthesis of esters") == []
    assert infer_tags("https://x.com/alice/status/1", "hello world from a chemist") == []
    # github keyword still matches TAG_RULES (high-signal), but not the old
    # "github.com → coding+research" fallback that always padded research.
    github_only = infer_tags("https://github.com/org/repo", "Random readme blurb")
    assert "research" not in github_only


def test_infer_tags_high_signal_rules_still_match():
    tags = infer_tags("Deploy with Docker and Kubernetes on an NVIDIA A100 GPU")
    assert "infra" in tags
    assert "gpu" in tags


def test_clean_tags_prefers_analysis_tags_without_junk_padding():
    """Agent/API analysis tags stay; no domain fallback pads the list."""
    got = clean_tags(
        ["catalysis", "organic-synthesis"],
        "https://example.com/doi/10.1021/example",
        "A methods paper on ester synthesis",
    )
    assert got[:2] == ["catalysis", "organic-synthesis"]
    assert "research" in got  # from TAG_RULES keyword "paper"/"methods"? "paper" in text
    # Must not invent ai-tools / generic-only fillers from the host
    assert "ai-tools" not in got


def test_clean_tags_empty_existing_stays_empty_without_signal():
    assert clean_tags([], "https://example.com/a", "plain prose about cooking") == []
