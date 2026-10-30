# AGENTS.md

**A pasted URL means: finish it.** If the user's message is or contains a URL,
run the whole flow without stopping or asking: `python3 forge add <url> --agent`,
read `data/pending/<id>.content.md`, write `data/pending/<id>.analysis.json`
(shape in `skills/forger/SKILL.md`), run `python3 forge resolve <id>`, then
reply with the finished bookmark (title, bucket, reason). Stopping after `add`
leaves the bookmark pending — that is a failure.

Forger turns a pasted URL into a scored bookmark. Python package in `forger/`,
CLI in `forge.py`, optional Next.js dashboard in `web/`. The owner reviews
results, not code, so the code and its checks carry the rules below.

## Check your work

- Python: `.venv/bin/pytest -q` (CI: `tests` job, Python 3.10 and 3.12).
- Agent path without openai: CI job `agent-no-openai` (also
  `tests/test_lazy_openai_import.py`).
- Dashboard, when you touch `web/`: `cd web && npm ci && npm run lint && npx tsc --noEmit && npm run test:shared && npm run build` (CI: `web` job, Node 24).
- Shared text rules (tags, search, truncation): `tests/fixtures/shared_cases/text_rules.json` — checked by pytest and `npm run test:shared`.
- Report the exact pass/fail counts you saw. If you could not run something, say so.

## Rules and what enforces them

When code enforces a rule, trust the check and keep it passing. "Prose only"
means nothing fails if you break the rule, so take extra care there.

| Rule | Enforced by |
|---|---|
| Refuse trash: an empty, thin, link-only or bot-challenge scrape is never saved, and agent mode never fills it in later. `forge add` answers `SCRAPE_FAILED`. | `forger.scrape_result.scrape_url` returns `Saved` \| `Refused`; only `Saved` becomes a bookmark (`forger/bookmark_workflow.py`). Replay: `tests/test_scrape_replay.py`. Boundary: `tests/test_scrape_boundary.py`. Quality helpers still live in `forger/scrape_quality.py`. |
| Agent mode must not require the `openai` package. Core install stays openai-free. | Lazy import in `forger/analysis.py`; CI job `agent-no-openai`; `tests/test_lazy_openai_import.py`. |
| Pending is first-class: agent add writes the bookmark + pending content only — never a placeholder `AnalysisResult`. Stats pending counts the pending dir. | `forger.models.is_pending_analysis` / `pending_content_ids` / `finished_analyses`; `tests/test_pending_first_class.py`. |
| `agent_tags` is the source of truth vs inferred tags. `retag` refreshes inferred only; never strip agent-owned tags. No `forge retag --agent` yet. | `Bookmark.agent_tags` in `forger/models.py`; `forger.tagging.retag`; `tests/test_tag_whole_words.py`. |
| Optional analysis text uses one ingest path; string-null (`"None"`, `"null"`, …) becomes real `None`. | `forger.models.ingest_optional_analysis_text`; used by resolve + analysis; `tests/test_resolve_none_strings.py`. |
| New scrapers should return `Saved` \| `Refused`, not grow `{success: …}` dicts. PubChem is peeled; leftover success-dicts are budgeted. | `forger/scrapers/pubchem.py`; convert at the edge via `forger.scrapers._legacy_dict`; lint `tests/test_no_new_success_dicts.py`. |
| Dashboard sync exports through models (kebab tags, card-truncated summary, `display_title`). | `forger.dashboard_sync.export_dashboard_payloads`; golden `tests/fixtures/dashboard_export/golden.json`; `tests/test_dashboard_sync.py`. |
| No video scraping: don't add code that downloads or transcribes video. Video URLs are bookmarked from their page text only. | Prose only |
| Work on a branch and open a PR. The owner merges. Don't push or open a PR until the owner says so. | Prose only |
| Never force-push or rewrite `main`. | Prose only. `main` has no branch protection on GitHub yet (P0 waits on the owner). |
| No personal data in commits: no emails, real names, tokens or user bookmark data. Commit as the GitHub noreply address. | `gitleaks` CI job (secrets only, not names or emails); `.gitignore` keeps `data/` out. The rest is prose only |
| Never report a green result you didn't see. | CI `tests` + `agent-no-openai` + `web` + `gitleaks` on every PR and push to `main` (shows real results, but doesn't block a merge while `main` is unprotected) |
| Write to the owner in plain English: what changed for them, with one concrete before/after example, then the details. | Prose only |
| Don't touch `/workspace/forger-users/` (tester data). | Prose only |

## When the owner corrects you

Fix the mistake, then add or update a row here. If the rule was already listed
as prose only and it happened again, enforce it in code or a test in the same
change (a type, a check at the boundary, or a failing test), and point the row
at that enforcer. Delete a row once code makes the mistake impossible.
