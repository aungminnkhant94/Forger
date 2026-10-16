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
    ("trading", ("trading", "forex", "crypto", "btc", "bitcoin", "polymarket", "market")),
    ("security", ("security", "vulnerability", "exploit", "permission", "sandbox", "hardening")),
    ("research", ("paper", "research", "benchmark", "evaluation", "study")),
    ("performance", ("performance", "speedup", "latency", "throughput", "optimization")),
]


def _normalize(text: str) -> str:
    return text.lower().replace("_", " ")


def infer_tags(*parts: str | None, limit: int = 5) -> list[str]:
    """Return high-signal tags from TAG_RULES keyword hits only.

    No URL/domain fallbacks — inventing "research" / "ai-tools" / "coding"
    just because the host is example.com / x.com / github.com pollutes
    bookmarks before real analysis (especially agent mode: add → pending →
    resolve). Empty is better than junk; resolve/API analysis supplies tags.
    """
    haystack = " ".join(_normalize(p or "") for p in parts)
    tags: list[str] = []
    for tag, keywords in TAG_RULES:
        if any(keyword in haystack for keyword in keywords):
            tags.append(tag)
    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[:limit]


def clean_tags(existing: Iterable[str] | None, *parts: str | None, limit: int = 5) -> list[str]:
    cleaned = [t for t in normalize_tags(existing) if t != "general"]
    inferred = infer_tags(*parts, limit=limit)
    final: list[str] = []
    for tag in [*cleaned, *inferred]:
        if tag and tag not in final:
            final.append(tag)
    return final[:limit]
