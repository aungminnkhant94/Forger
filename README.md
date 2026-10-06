# RolloForge

**Paste a URL. Your AI agent turns it into a scored, searchable knowledge base.**

RolloForge is a headless bookmark engine for AI agents. Install the skill into any SKILL.md-compatible agent — Claude Code, Codex, Kimi Code CLI, ZCode, Cursor, OpenCode, Hermes, and 30+ more — and every link you paste in a normal chat gets scraped, judged against **your** profile, bucketed, and stored with a dashboard to browse it all.

```
URL  →  scrape  →  score against profile.md  →  bucket  →  store  →  dashboard
```

No bot to host. No account. The agent you already use is the front door; RolloForge is the engine behind it.

## What it does

- **Scrape** — articles via requests + BeautifulSoup; X/Twitter and JS-heavy pages via Playwright (optional).
- **Score** — an LLM reads the full content *and your `profile.md`*, then answers three honest questions: actionable this week? reduces friction on something you're building? worth keeping as reference?
- **Bucket** — every bookmark lands in `test_this_week` / `build_later` / `archive` / `ignore`, with a blunt one-line reason.
- **Store** — JSON + SQLite under `data/`, yours entirely, offline.
- **Browse** — a Next.js dashboard with search, filters and stats; or just ask your agent: *"what's in my forge about docker?"*

The differentiator is **bring-your-own-profile**: scoring is personal, not generic. You write one plain-text file about yourself and your work; every analysis reads it.

## Install as a skill (any agent)

```bash
npx skills add aungminnkhant94/RolloForge
```

Pick your agent(s) in the interactive prompt (Claude Code, Codex, Cursor, OpenCode, Kimi Code CLI, ...). Hermes users: `hermes skills install aungminnkhant94/RolloForge/rolloforge`.

Then just tell your agent in a normal chat:

> install rolloforge and set it up

The agent reads the skill, installs the engine, interviews you briefly to write your `profile.md`, and you paste your first URL. That first bookmark landing on your dashboard — scored, bucketed, tagged — is the whole setup verification.

## Manual install (no agent)

```bash
git clone https://github.com/aungminnkhant94/RolloForge.git
cd RolloForge
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # optional — X links and JS-heavy pages
cp .env.example .env                 # add ONE LLM API key
cp profile.example.md profile.md     # describe yourself — this drives all scoring
python forge add https://example.com/some-article
python forge stats
```

## Configuration (`.env`)

| Variable | What |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek key (default provider) |
| `ANALYSIS_PROVIDER=kimi` + `KIMI_API_KEY` | Use Kimi |
| `ANALYSIS_PROVIDER=custom` + `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` | Any OpenAI-compatible API (GLM, OpenAI, Ollama, ...) |
| `ROLLOFORGE_PROFILE` | Path to your profile (default `./profile.md`) |
| `ROLLOFORGE_EXTRA_CONTEXT_DIR` | Optional folder of `.md` notes searched for extra context |
| `X_COOKIES_PATH` | Optional X cookies JSON for tweet scraping |

## The CLI

```
forge add <url>          scrape → score → store → sync dashboard
forge add <url> --agent  agent mode: no API key — saves content for YOUR agent to analyze
forge resolve <id>       ingest the agent-written analysis (completes agent mode)
forge search <q>         full-text search across everything
forge stats              counts, bucket distribution, priorities
forge digest             weekly digest (md/html)
forge export             dump JSON/CSV
forge sync               copy data/ into web/ for the dashboard
forge health             checks
```

**Agent mode** is the zero-key path: `forge add --agent` stores the scraped content under `data/pending/`, the agent reads it, writes its own analysis JSON (same three questions), and `forge resolve` ingests it. This is how the skill runs RolloForge with no LLM API key at all — the agent you already pay for does the scoring.

## Dashboard

```bash
cd web && npm install && npm run dev
```

Deploy anywhere (Vercel: root directory `web`). See `web/README.md`.

## Integrations

- `skills/rolloforge/` — the agent skill (the main interface)
- `integrations/telegram/` — optional always-on Telegram bot lane, for setups without an agent harness

## License

MIT
