from __future__ import annotations

import re
from typing import Iterable

# Canonical tag form: lowercase kebab-case ("machine-learning"), matching
# TAG_RULES and the analysis prompts. Spaces/underscores become hyphens.
_TAG_SEP_RE = re.compile(r"[\s_\-]+")


def normalize_tag(tag: object) -> str:
    """Return the canonical form of *tag* ("Machine Learning" -> "machine-learning")."""
    text = str(tag or "").strip().lower().lstrip("#").strip()
    return _TAG_SEP_RE.sub("-", text).strip("-")


def normalize_tags(tags: Iterable[object] | None) -> list[str]:
    """Normalize, drop empties, and dedupe while keeping first-seen order."""
    out: list[str] = []
    for tag in tags or []:
        norm = normalize_tag(tag)
        if norm and norm not in out:
            out.append(norm)
    return out

TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("agents", ("agent", "agents", "agentic", "multi-agent", "orchestration")),
    ("multi-agent", ("multi-agent", "swarm", "orchestrator", "parallel workers")),
    ("automation", ("automation", "automate", "workflow", "pipeline", "cron")),
    ("ai-tools", ("ai tool", "ai tools", "tool use", "coding assistant", "assistant")),
    ("llm", ("llm", "language model", "model routing", "openai", "anthropic", "deepseek", "moonshot", "qwen", "gpt", "claude", "kimi")),
    ("kimi", ("kimi", "moonshot")),
    ("qwen", ("qwen", "alibaba qwen")),
    ("claude", ("claude", "anthropic")),
    ("coding", ("coding", "code", "github", "repo", "repository", "programming", "developer")),
    ("gpu", ("gpu", "cuda", "cutlass", "a100", "a6000", "nvidia")),
    ("infra", ("infra", "docker", "server", "deployment", "deploy", "kubernetes", "vm", "vps")),
    ("trading", ("trading", "forex", "crypto", "btc", "bitcoin", "polymarket")),
    ("security", ("security", "vulnerability", "exploit", "permission", "sandbox", "hardening")),
    ("research", ("paper", "research", "researcher", "benchmark", "evaluation", "study", "studies")),
    ("performance", ("performance", "speedup", "latency", "throughput", "optimization")),
]


def _normalize(text: str) -> str:
    return text.lower().replace("_", " ")


def _keyword_re(keyword: str) -> re.Pattern[str]:
    # Whole words only: "agent" must not match "agency", "market" not "marketing".
    # Plain inflections are allowed ("papers", "automated", "coders").
    return re.compile(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?:s|es|d|ed|ing|er|ers)?(?![a-z0-9])")


_RULE_PATTERNS: list[tuple[str, tuple[re.Pattern[str], ...]]] = [
    (tag, tuple(_keyword_re(k) for k in keywords)) for tag, keywords in TAG_RULES
]
RULE_TAGS = frozenset(tag for tag, _ in TAG_RULES)


def infer_tags(*parts: str | None, limit: int = 5) -> list[str]:
    """Return high-signal tags from TAG_RULES keyword hits only.

    No URL/domain fallbacks — inventing "research" / "ai-tools" / "coding"
    just because the host is example.com / x.com / github.com pollutes
    bookmarks before real analysis (especially agent mode: add → pending →
    resolve). Empty is better than junk; resolve/API analysis supplies tags.
    """
    haystack = " ".join(_normalize(p or "") for p in parts)
    tags: list[str] = []
    for tag, patterns in _RULE_PATTERNS:
        if any(p.search(haystack) for p in patterns):
            tags.append(tag)
    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[:limit]


def clean_tags(existing: Iterable[str] | None, *parts: str | None, limit: int = 5) -> list[str]:
    """Analysis (agent/API) tags win; keyword inference only fills an empty list."""
    cleaned = [t for t in normalize_tags(existing) if t != "general"]
    if cleaned:
        return cleaned[:limit]
    inferred = infer_tags(*parts, limit=limit)
    final: list[str] = []
    for tag in [*cleaned, *inferred]:
        if tag and tag not in final:
            final.append(tag)
    return final[:limit]


def _substring_rule_tags(*parts: str | None) -> set[str]:
    """Rule tags the old substring matcher produced (to spot its leftovers)."""
    haystack = " ".join(_normalize(p or "") for p in parts)
    legacy = {"trading": ("market",)}  # keyword dropped from TAG_RULES
    return {
        tag for tag, keywords in TAG_RULES
        if any(k in haystack for k in (*keywords, *legacy.get(tag, ())))
    }


def retag(tags: Iterable[str] | None, *parts: str | None) -> list[str]:
    """Drop rule tags that only the old substring matching produced.

    Saved bookmarks do not record which tags came from the agent and which
    from inference. A tag is removed only when (1) it is a TAG_RULES tag,
    (2) the old substring matcher would have produced it from this text, and
    (3) whole-word matching no longer does. A rule tag with no substring
    evidence in the text was chosen by the agent, so it is kept, as is every
    non-rule tag.
    """
    current = normalize_tags(tags)
    supported = set(infer_tags(*parts, limit=len(TAG_RULES)))
    substring_only = _substring_rule_tags(*parts) - supported
    return [t for t in current if t not in substring_only]
