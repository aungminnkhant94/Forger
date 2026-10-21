## What changed for the user

One concrete before → after.

## How you verified

- [ ] `.venv/bin/pytest -q` (exact pass count)
- [ ] CI: `tests (3.10)`, `tests (3.12)`
- [ ] CI: `agent-no-openai` (when agent / openai import path touched)
- [ ] CI: `web` (when `web/` touched)
- [ ] CI: `gitleaks`

## What the owner must judge

Risk / product call — not “all green.”

## Guardrails

- [ ] No personal data, tokens, or user bookmark data in commits
- [ ] No force-push / rewrite of `main`
