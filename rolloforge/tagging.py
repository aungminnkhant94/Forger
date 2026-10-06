from __future__ import annotations

from typing import Iterable

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
    haystack = " ".join(_normalize(p or "") for p in parts)
    tags: list[str] = []
    for tag, keywords in TAG_RULES:
        if any(keyword in haystack for keyword in keywords):
            tags.append(tag)
    if not tags:
        if "github.com" in haystack:
            tags.extend(["coding", "research"])
        elif "x.com" in haystack or "twitter.com" in haystack:
            tags.append("ai-tools")
        else:
            tags.append("research")
    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[:limit]


def clean_tags(existing: Iterable[str] | None, *parts: str | None, limit: int = 5) -> list[str]:
    cleaned = [t.strip().lower() for t in (existing or []) if t and t.strip().lower() != "general"]
    inferred = infer_tags(*parts, limit=limit)
    final: list[str] = []
    for tag in [*cleaned, *inferred]:
        if tag and tag not in final:
            final.append(tag)
    return final[:limit]
