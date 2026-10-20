"""Freeze leftover ``"success"`` scrape dicts; peeled adapters must not add more.

P5 peeled PubChem to ScrapeOutcome. Remaining dict emitters live under a budget.
New ``"success"`` dict keys outside the allowlist (or over budget) fail this check.
Prefer :mod:`forger.scrapers._legacy_dict` when a legacy dict is still required.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Budgets after the PubChem peel. Raising a number needs an explicit PR reason.
# _legacy_dict.py is the sanctioned conversion path for peeled adapters.
SUCCESS_DICT_BUDGET: dict[str, int] = {
    "forger/scrapers/_legacy_dict.py": 2,
    "forger/scrapers/article_scraper.py": 12,
    "forger/scrapers/doi_metadata.py": 2,
    "forger/scrapers/hacker_news.py": 3,
    "forger/scrapers/x_scraper.py": 9,
}


def _success_dict_key_count(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "success":
                    count += 1
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    sl = target.slice
                    if isinstance(sl, ast.Constant) and sl.value == "success":
                        count += 1
    return count


def test_no_new_success_dicts_outside_budget():
    """Any forger/ file with success-dict keys must be allowlisted and under budget."""
    offenders: list[str] = []
    seen: dict[str, int] = {}
    for path in sorted((ROOT / "forger").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        n = _success_dict_key_count(path)
        if n == 0:
            continue
        seen[rel] = n
        budget = SUCCESS_DICT_BUDGET.get(rel)
        if budget is None:
            offenders.append(f"{rel}: {n} \"success\" dict key(s) (not allowlisted)")
        elif n > budget:
            offenders.append(f"{rel}: {n} \"success\" dict key(s) (budget {budget})")

    # Peeled PubChem must stay at zero.
    pubchem = "forger/scrapers/pubchem.py"
    assert _success_dict_key_count(ROOT / pubchem) == 0, (
        f"{pubchem} must not emit \"success\" dicts after the P5 peel"
    )

    assert not offenders, (
        "New or over-budget \"success\" scrape dicts:\n  - "
        + "\n  - ".join(offenders)
        + "\nConvert at the edge via forger.scrapers._legacy_dict or raise the "
        "budget only when peeling is impossible."
    )

    # Budgets must match reality so the freeze does not silently drift down.
    for rel, budget in SUCCESS_DICT_BUDGET.items():
        actual = seen.get(rel, 0)
        assert actual == budget, (
            f"{rel}: expected exactly {budget} \"success\" dict key(s), found {actual}. "
            "Update SUCCESS_DICT_BUDGET when a peel removes leftovers."
        )
