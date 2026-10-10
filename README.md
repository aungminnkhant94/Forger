# Forger

**Turn saved links into things you’ll actually use—with the AI agent you already have.**

Found an article, guide, or tool you want to come back to? Paste its URL into your agent chat. Forger reads the page, checks it against a short profile of what you're working on, and recommends what deserves your attention—with a clear reason.

Add a note like *"I'm saving this for my deployment project"* to tell your agent why the link matters. Your own words guide the recommendation.

## Demo

https://github.com/user-attachments/assets/0d871d04-daa7-4756-930d-220259fbcd4f

One link goes in — the agent reads it, scores it against your profile, and the dashboard files it: **Test This Week**, **Build Later**, **Archive**, or a confident **Ignore**. Made with the [`/brag`](https://github.com/latent-spaces/brag) skill.

## Decide what to do with each link

- **Try this week** — something you can act on now.
- **Build later** — something that could help a project you're working on.
- **Keep as reference** — something worth finding again when you need it.
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

> **Agents:** the full operating manual is [`skills/forger/SKILL.md`](skills/forger/SKILL.md) — written for you, not for humans. Read it first.

## Manual install (no agent)

**Prerequisites:** Python 3.10+ and git. Node 20.9+ only if you want the dashboard. Playwright chromium only for X/Twitter and JS-heavy pages. No API key required for agent mode.

```bash
git clone https://github.com/aungminnkhant94/Forger.git
cd Forger
python3 -m venv .venv && source .venv/bin/activate   # Windows: py -3 -m venv .venv, then .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium                           # optional — X links and JS-heavy pages
cp profile.example.md profile.md                      # REQUIRED — edit it: this drives all scoring
cp .env.example .env                                  # only for API-mode scoring — add ONE key (see table below)
```

**Verify the install:**

```bash
python forge health          # should end with "Health Check Passed"
python forge add https://example.com --agent    # saves a bookmark; content lands in data/pending/
python forge stats           # should show 1 bookmark
```

With an API key in `.env`, use `python forge add <url>` (the API scores it). Without a key, `forge add` without `--agent` still saves but the analysis degrades to a fallback stub — prefer `--agent` or configure a key.

## Configuration (`.env`)

| Variable | What |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek key (default provider) |
| `ANALYSIS_PROVIDER=kimi` + `KIMI_API_KEY` | Use Kimi |
| `ANALYSIS_PROVIDER=custom` + `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` | Any OpenAI-compatible API (GLM, OpenAI, Ollama, ...) |
| `FORGER_PROFILE` | Path to your profile (default `./profile.md`) |
| `FORGER_EXTRA_CONTEXT_DIR` | Optional folder of `.md` notes searched for extra context |
| `X_COOKIES_PATH` | Optional X cookies JSON for tweet scraping |

## The CLI

```
forge add <url>          scrape → score → store → sync dashboard
forge add <url> --agent  agent mode: no API key — saves content for YOUR agent to analyze
forge add <url> --note ".."  pass the user's own words with the link — strongest analysis signal
forge resolve <id>       ingest the agent-written analysis (completes agent mode)
forge search <q>         full-text search across everything
forge stats              counts, bucket distribution, priorities
forge digest             weekly digest (md/html)
forge export             dump JSON/CSV
forge sync               sync dashboard (public JSON empty by default; --publish for real data)
forge health             checks
```

**Agent mode** is the zero-key path: `forge add --agent` stores the scraped content under `data/pending/`, the agent reads it, writes its own analysis JSON (same three questions), and `forge resolve` ingests it. This is how the skill runs Forger with no LLM API key at all — the agent you already pay for does the scoring.

## Dashboard

```bash
cd web && npm install && npm run dev     # needs Node 20.9+ (repo pins 24.x; tested on 24)
```

Deploy anywhere (Vercel: root directory `web`). See `web/README.md`.

## Integrations

- `skills/forger/` — the agent skill (the main interface)
- `integrations/telegram/` — optional always-on Telegram bot lane, for setups without an agent harness

## License

MIT
