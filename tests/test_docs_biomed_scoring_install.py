"""Docs contract: scoring anti-all-archive rule + no Forger self-add setup URL."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORGER_SELF_ADD = "forge add https://github.com/aungminnkhant94/Forger"
ANTI_ARCHIVE_MARKERS = (
    "all science = archive",
    "do NOT park every on-profile paper",
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_readme_and_skill_avoid_forger_self_add_url():
    readme = _read("README.md")
    skill = _read("skills/forger/SKILL.md")
    setup = _read("skills/forger/references/setup.md")
    assert FORGER_SELF_ADD not in readme
    assert FORGER_SELF_ADD not in skill
    assert "Never" in skill and "aungminnkhant94/Forger" in skill
    assert "Never" in setup and "aungminnkhant94/Forger" in setup
    assert "en.wikipedia.org" in readme or "pubmed" in readme.lower()


def test_analysis_and_skill_mention_anti_all_archive_rule():
    analysis = _read("skills/forger/references/analysis.md")
    skill = _read("skills/forger/SKILL.md")
    for text in (analysis, skill):
        assert any(m in text for m in ANTI_ARCHIVE_MARKERS), text[:200]
    assert "test_this_week" in analysis and "worth" in analysis.lower()
    assert "build_later" in analysis
    assert "6.5" in analysis or "~6.5" in analysis
    assert "PCR" in analysis or "assay" in analysis.lower() or "biomed" in analysis.lower()
