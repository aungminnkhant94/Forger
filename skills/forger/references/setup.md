# Forger Setup Details

## Prerequisites

| Need | For | Check |
|---|---|---|
| Python 3.10+ | engine | `python3 --version` |
| git | cloning, optional auto-git | `git --version` |
| Node 18+ | dashboard only | `node --version` |
| Playwright chromium | X/Twitter + JS-heavy pages | `playwright install chromium` |

Everything else (`data/`, `reports/`) is auto-created on first run.

## Engine install

```bash
git clone https://github.com/aungminnkhant94/Forger.git ~/Forger
python3 -m venv .venv && . .venv/bin/activate
# Windows:  py -3 -m venv .venv  then  .venvScriptsctivate
python3 -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
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

## X/Twitter links

X blocks anonymous scraping. Options:
1. Export cookies from a logged-in browser session to JSON, point
   `X_COOKIES_PATH` at it in `.env` (best quality).
2. No cookies: X links save a stub — ask the user to paste the tweet text and
   mention it in your analysis (you can fold pasted text into the summary).
3. `playwright install chromium` improves JS-page scraping generally.

## Dashboard

```bash
cd web && npm install && npm run dev     # http://localhost:3000
```

Data flows one way: `forge` writes `data/*.json`, `forge sync` copies them to
`web/lib/` and `web/public/` (sync runs automatically after every add/resolve).
Deploy: any static host; on Vercel set Root Directory to `web`.

## Optional extras

- Auto git push of new bookmarks: set `FORGER_AUTO_GIT=1` (repo needs a
  remote). Off by default.
- Extra context: `FORGER_EXTRA_CONTEXT_DIR=/path/to/notes` — paragraphs
  matching each bookmark get injected as additional context (API mode).
- Always-on Telegram bot instead of an agent: see `integrations/telegram/`.
