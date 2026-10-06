---
name: forger
description: Turn URLs the user pastes into a scored, searchable personal knowledge base. Use when the user shares or asks to save a link, wants to find something they saved, asks about their bookmarks/forge, or wants the Forger engine installed or fixed. Headless pipeline — scrape, score against the user's profile, bucket, store, dashboard.
---

# Forger

Forger is a personal bookmark engine: URL → scrape → score against the
user's `profile.md` → bucket (`test_this_week` / `build_later` / `archive` /
`ignore`) → local storage → optional web dashboard. You are the analyst: in
agent mode YOU score the content — no API key needed.

Default install location: `~/Forger` (any dir works; remember where you
installed it). All commands below assume you `cd` there first.

## First-time setup (once per user)

1. **Check prerequisites**: Python 3.10+ (`python3 --version`). Git. Optional:
   Node 18+ (dashboard), Playwright chromium (X/Twitter links).
2. **Get the engine**:
   ```
   git clone https://github.com/aungminnkhant94/Forger-oss.git ~/Forger
   cd ~/Forger
   python3 -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
   No git? Download the repo zip and extract.
   **Safety**: if the target directory already exists and is not a Forger
   checkout (no `forge.py` inside), do NOT touch or clone into it — pick a
   different directory (e.g. `~/Forger-oss`) and remember it. Never run
   forge commands inside a directory that belongs to another project.
3. **Create the profile** — interview the user briefly (2-4 questions), then
   write their answers into `~/Forger/profile.md` following
   `profile.example.md`: who they are, what they're building now, always-relevant
   topics, actively-ignore topics. The profile drives ALL scoring — richer
   profile, better scores. Show them the file when done.
4. **LLM key — optional.** Without any key, use agent mode (below) and score
   bookmarks yourself. If the user wants automated scoring instead, help them
   put ONE provider block in `.env` (copy from `.env.example`): DeepSeek, Kimi,
   or any OpenAI-compatible API.
5. **Verify**: `python forge health` then run the first bookmark through agent
   mode (next section). That completed bookmark IS the setup check.
6. **Optional dashboard**: `cd web && npm install && npm run dev` (needs Node).

## When the user pastes a URL (the main flow)

No key required — you are the analyst:

1. `python forge add <url> --agent`
   - Saves the bookmark, scrapes content, prints a `bookmark_id`.
   - Scraped content is written to `data/pending/<id>.content.md`.
   - If it says DUPLICATE, tell the user it's already saved (optionally show the
     existing entry via `python forge search <title>`).
2. Read `data/pending/<id>.content.md` (and open the URL yourself if the
   scrape looks thin).
3. Analyze it against the user's `profile.md` — see the Analysis Contract in
   `references/analysis.md`. Write your analysis to
   `data/pending/<id>.analysis.json` using exactly this shape:
   ```json
   {
     "title": "Polished title",
     "summary": "3-4 sentences: what it is, takeaway, why it matters to THIS user",
     "recommendation_reason": "One blunt sentence: why relevant or not, right now",
     "relates_to": "2-4 sentences tying it to the user's goals from profile.md, or say nothing connects",
     "key_insights": ["3-5 concrete takeaways"],
     "tags": ["2-6 specific tags"],
     "actionable_this_week": false,
     "reduces_friction": false,
     "reference_material": false,
     "recommendation_bucket": "test_this_week"
   }
   ```
   Bucket rules: `test_this_week` = actionable within 7 days. `build_later` =
   reduces friction on something they're building. `archive` = worth finding
   again later. `ignore` = none of these. When torn, choose the MORE urgent.
   Judge against THEIR profile, never a generic tech audience. Be strict.
4. `python forge resolve <bookmark_id>`
5. Report back in one short block: title, bucket, your one-line reason. Done.

If the user configured an LLM key in `.env`, step 1 becomes plain
`python forge add <url>` (the API scores it) — then just report the result.

## When the user asks about their saved stuff

- Find things: `python forge search "<topic>"`
- Overview: `python forge stats`
- Weekly report: `python forge digest --days 7`
- Raw data: `data/bookmarks_raw.json`, `data/analysis_results.json`
- Answer from the results; cite the bucket and reason so they learn what the
  forge thinks of their stream.

## Troubleshooting

See `references/troubleshooting.md`. Common cases: X links need cookies
(`X_COOKIES_PATH`) or fall back to a stub; JS-heavy pages need
`playwright install chromium`; missing `data/` dirs are auto-created.

## References

- `references/setup.md` — full install details, provider config, dashboard, deploy
- `references/analysis.md` — the analysis contract: judgment rules and scoring
- `references/troubleshooting.md` — failure modes and fixes
