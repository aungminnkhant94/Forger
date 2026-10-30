# Forger Setup Details

## Prerequisites

| Need | For | Check |
|---|---|---|
| Python 3.10+ | engine | `python3 --version` |
| git | cloning, optional auto-git | `git --version` |
| Node 20.9+ (repo pins 24.x) | dashboard only | `node --version` |
| Playwright chromium | X/Twitter + JS-heavy pages | `playwright install chromium` |

Everything else (`data/`, `reports/`) is auto-created on first run.

## Engine install

```bash
git clone https://github.com/aungminnkhant94/Forger.git ~/Forger
cd ~/Forger
python3 -m venv .venv && . .venv/bin/activate
# Windows:  py -3 -m venv .venv   then   .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # only needed for API-mode scoring
cp profile.example.md profile.md   # then interview the user and rewrite it
```

No internet-friendly git? Download the zip, extract, continue from step 2.

## The profile interview

The profile drives every score. Ask the user 2-4 natural questions, not a form:

1. What are you working on / building right now?
2. What topics do you never want to miss?
3. What should I actively ignore?
4. (optional) What's your preferred default — act now or keep for later?

Write `profile.md` from their answers (structure per `profile.example.md`).
Show it to them for a thumbs-up. It's a living file — update it whenever the
user's focus shifts; just mention you did.

## LLM provider (optional — agent mode needs none)

`.env` picks exactly one:

```
# DeepSeek (default)
DEEPSEEK_API_KEY=sk-...

# Kimi
ANALYSIS_PROVIDER=kimi
KIMI_API_KEY=...

# Any OpenAI-compatible API (GLM, OpenAI, Ollama, ...)
ANALYSIS_PROVIDER=custom
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_API_KEY=...
LLM_MODEL=glm-4.7
```

With a key configured, `python forge add <url>` scores automatically via the
API. Without one, always use `--agent` and score it yourself.

## Setup-check bookmark (first verify)

For the first verify bookmark, use a **neutral third-party URL** with real
content (e.g. `https://en.wikipedia.org/wiki/Bookmark_(digital)` or a short
PubMed page). **Never** save `https://github.com/aungminnkhant94/Forger`
(or this repository's own URL / README) as the setup-check bookmark — the
check must prove scrape → score works on an ordinary page, not on Forger itself.

## X/Twitter links

Public status URLs are scraped **without X cookies** via Twitter syndication /
oEmbed (and a fxtwitter JSON fallback). No Playwright and no yt-dlp required
for ordinary public tweets.

Optional upgrade:
1. Export cookies from a logged-in browser session to JSON, point
   `X_COOKIES_PATH` at it in `.env` — Playwright then runs as a fallback for
   gated or flaky posts.
2. `playwright install chromium` also helps other JS-heavy pages.
3. If a rare public API miss still fails, ask the user to paste the tweet text.

## Dashboard

```bash
cd web && npm install && npm run dev     # http://localhost:3000
```

Data flows one way: `forge` writes `data/*.json`, then syncs the dashboard.
By default `web/public/*.json` is written as empty `[]` so deploys cannot leak
personal bookmarks. To view real data locally: `forge sync --publish` or set
`FORGER_PUBLISH_DASHBOARD=1`. Deploy: any static host; on Vercel set Root
Directory to `web`. The public dashboard is read-only (no remote edit/delete).

## Optional extras

- Publish dashboard JSON: `FORGER_PUBLISH_DASHBOARD=1` or `forge sync --publish`
  (off by default).
- Auto git push of new bookmarks: set `FORGER_AUTO_GIT=1` (repo needs a
  **private** remote). Off by default; Forger prints a hard warning when
  enabled because it can commit personal data.
- Extra context: `FORGER_EXTRA_CONTEXT_DIR=/path/to/notes` — paragraphs
  matching each bookmark get injected as additional context (API mode).
- Always-on Telegram bot instead of an agent: see `integrations/telegram/`.
