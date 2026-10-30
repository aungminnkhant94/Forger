# Forger

**Turn saved links into things you’ll actually use—with the AI agent you already have.**

Found an article, guide, or tool you want to come back to? Paste its URL into your agent chat. Forger reads the page, checks it against a short profile of what you're working on, and recommends what deserves your attention—with a clear reason.

Add a note like *"I'm saving this for my deployment project"* to tell your agent why the link matters. Your own words guide the recommendation.

## Demo

https://github.com/user-attachments/assets/0d871d04-daa7-4756-930d-220259fbcd4f

One link goes in — the agent reads it, scores it against your profile, and the dashboard files it: **Test This Week**, **Build Later**, **Archive**, or a confident **Ignore**. Made with the [`/brag`](https://github.com/latent-spaces/brag) skill.

## Decide what to do with each link

- **Test This Week** — something you can act on now.
- **Build Later** — something that could help a project you're working on.
- **Archive** — something worth finding again when you need it.
- **Ignore** — something that doesn't fit your current needs.

Your profile describes your current projects and interests, so recommendations reflect what matters to you.

## Find it again when you need it

Your bookmarks are stored in local files. Search through your agent—*"what's in my forge about Docker?"*—or browse the optional dashboard with search, filters, and summaries.

**No additional LLM API key required in agent mode.** Your existing agent handles the analysis. You can also connect an LLM API for automated scoring.

## Install as a skill (any agent)

```bash
npx skills add aungminnkhant94/Forger
```

Pick your agent(s) in the interactive prompt (Claude Code, Codex, Cursor, OpenCode, Kimi Code CLI, ...). Hermes users: `hermes skills install aungminnkhant94/Forger/forger`.

Then just tell your agent in a normal chat:

> install forger and set it up

The agent reads the skill, installs the engine, interviews you briefly to write your `profile.md`, and you paste your first URL. That first bookmark landing on your dashboard — scored, bucketed, tagged — is the whole setup verification.

> **Agents:** the full operating manual is [`skills/forger/SKILL.md`](skills/forger/SKILL.md) — written for you, not for humans. Read it first. Contributors: [`AGENTS.md`](AGENTS.md) lists the project rules and the code that enforces each one.

## Manual install (no agent)

**Prerequisites:** Python 3.10+ and git. Node 24 only if you want the dashboard. Playwright chromium optional (JS-heavy pages, login-gated X posts). Public X posts need no cookies or Playwright. No API key required for agent mode.

```bash
git clone https://github.com/aungminnkhant94/Forger.git
cd Forger
python3 -m venv .venv && source .venv/bin/activate   # Windows: py -3 -m venv .venv, then .venv\Scripts\activate
pip install -r requirements.txt
# Agent mode needs no openai; API scoring: pip install -r requirements-llm.txt  (or pip install '.[llm]')
playwright install chromium                           # optional — JS-heavy pages, login-gated X posts
cp profile.example.md profile.md                      # REQUIRED — edit it: this drives all scoring
cp .env.example .env                                  # only for API-mode scoring — add ONE key (see table below)
```

**Verify the install:**

```bash
python forge health          # should end with "Health Check Passed"
python forge add https://en.wikipedia.org/wiki/Bookmark_(digital) --agent    # saves a bookmark; content lands in data/pending/
python forge stats           # should show 1 bookmark
```

Use a page with real content (any third-party page works — Wikipedia, PubMed, a blog). Do **not** use this repo's own GitHub URL or README as the setup-check bookmark. Near-empty pages such as `https://example.com` are refused on purpose (`SCRAPE_FAILED`, nothing saved).

With an API key in `.env`, use `python forge add <url>` (the API scores it). Without a key, `forge add` without `--agent` still saves but the analysis degrades to a fallback stub — prefer `--agent` or configure a key.

## Configuration (`.env`)

| Variable | What |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek key (default provider) |
| `ANALYSIS_PROVIDER=kimi` + `KIMI_API_KEY` | Use Kimi |
| `ANALYSIS_PROVIDER=custom` + `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` | Any OpenAI-compatible API (GLM, OpenAI, Ollama, ...) |
| `FORGER_PROFILE` | Path to your profile (default `./profile.md`) |
| `FORGER_EXTRA_CONTEXT_DIR` | Optional folder of `.md` notes searched for extra context |
| `X_COOKIES_PATH` | Optional X cookies JSON — Playwright upgrade for login-gated posts (public posts work without it) |
| `FORGER_PUBLISH_DASHBOARD=1` | Copy real bookmarks into `web/public/` on sync (same as `--publish`). Off by default |
| `FORGER_AUTO_GIT=1` | Commit and push after each save. Off by default; it can publish your data |

## The CLI

```
forge add <url>          scrape → score → store → sync dashboard
forge add <url> --agent  agent mode: no API key — saves content for YOUR agent to analyze
forge add <url> --note ".."  pass the user's own words with the link — strongest analysis signal
forge add <url|id> --replace  re-scrape and overwrite an existing bookmark
forge resolve <id>       ingest the agent-written analysis (completes agent mode)
forge retag --agent --tag coding  dry run; --apply queues those bookmarks so your agent re-picks tags
forge search <q>         full-text search across everything
forge stats              counts, bucket distribution, priorities
forge digest             weekly digest (md/html)
forge export             dump JSON/CSV
forge sync               sync dashboard (public JSON empty by default; --publish for real data)
forge sync --push        also push the synced files to GitHub
forge config             show (--show) or edit (--edit) .env
forge health             checks
```

**Agent mode** is the zero-key path: `forge add --agent` stores the scraped content under `data/pending/`, the agent reads it, writes its own analysis JSON (same three questions), and `forge resolve` ingests it. This is how the skill runs Forger with no LLM API key at all — the agent you already pay for does the scoring.

`forge retag --agent` (scope with `--tag <tag>` or `--all`; dry run unless `--apply`) re-queues existing bookmarks the same way: the agent writes `{"tags": [...]}` to `data/pending/<id>.analysis.json` and `forge resolve <id>` makes those tags replace the inferred ones. Safe to re-run.

Minimal analysis JSON (`data/pending/<id>.analysis.json`):

```json
{
  "summary": "What the page is, in one or two sentences.",
  "recommendation_bucket": "build_later",
  "relates_to": "How this ties to a goal in profile.md. Two or more sentences, not N/A.",
  "actionable_this_week": false,
  "reduces_friction": true,
  "reference_material": true,
  "recommendation_reason": "Optional one-line reason.",
  "key_insights": ["optional"],
  "tags": ["optional"]
}
```

Required: `summary`, `recommendation_bucket` (`test_this_week`, `build_later`, `archive` or `ignore`), `relates_to` (2+ sentences, 40+ characters), and the three true/false fields. `forge resolve` rejects the file and says why if one is missing.

Running several `forge add` commands at once is safe: writes to the data files are locked, so none are lost.

## What saves and what doesn't

Every scrape either saves real content or is refused. A refused link prints `SCRAPE_FAILED` and nothing is stored, so your agent never fills in a page it couldn't read. Retry later with `forge add <url> --replace`.

- **Works:** X posts (including long posts; a post that is mostly a link also saves the linked article), news sites, blogs, GitHub, Hacker News items, WeChat articles.
- **Partial:** Nature and ACS papers save the title and abstract from Crossref when the site blocks the page (Nature only if an abstract exists). If no source has the full text of a long X post, the short version is saved and a warning is logged.
- **Refused by design:** video download or transcription (video links save from page text only); bot-check, captcha, empty and thin pages.
- **Commonly blocked by the site (HTTP 403):** APS journals, phys.org, The Atlantic, Medium, New Scientist.
- **Blocked:** private and local network addresses (localhost, 10.x, 192.168.x, etc.).

## Privacy defaults

- The dashboard's public JSON is empty unless you run `forge sync --publish` (or set `FORGER_PUBLISH_DASHBOARD=1`).
- Auto commit-and-push is off unless `FORGER_AUTO_GIT=1`.
- The deployed dashboard cannot edit or delete bookmarks; make changes locally with the CLI.

## Dashboard

```bash
cd web && npm install && npm run dev     # needs Node 24
```

Deploy anywhere (Vercel: root directory `web`). See `web/README.md`.

## Integrations

- `skills/forger/` — the agent skill (the main interface)
- `integrations/telegram/` — optional always-on Telegram bot lane, for setups without an agent harness

## License

MIT
