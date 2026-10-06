# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `python: command not found` | Windows/macOS launcher names | try `py -3` or `python3` |
| `forge add` exits with sqlite "unable to open database file" | very old checkout | pull latest; `data/` is auto-created since v1.0 |
| X link saved as a stub ("View on X for full content") | X login wall | set `X_COOKIES_PATH` (see setup.md) or ask the user to paste the tweet text |
| Article saved as "[URL content not available]" | site blocks bots or needs JS | `playwright install chromium`; or fetch the page yourself and fold the key content into your analysis JSON summary |
| `DUPLICATE: Already saved` | exact URL already in the forge | not an error — show the existing entry (`forge search <title>`) |
| `DUPLICATE_TOPIC` | near-identical topic exists | treat as duplicate unless the user insists; mention the similar one |
| `forge resolve` says "summary is required" / bucket invalid | malformed analysis JSON | re-check the JSON shape in analysis.md; bucket must be exactly one of the four values |
| API mode: "DEEPSEEK_API_KEY not set" (or LLM_BASE_URL) | `.env` missing or empty | copy `.env.example` → `.env`, fill one provider block; or just use `--agent` |
| API mode: every analysis is "malformed JSON" | model returns reasoning + JSON, parse fails | engine retries with a repair pass; if it persists switch model via `LLM_MODEL` |
| Dashboard shows nothing | `forge sync` not run or web not started | `python forge sync`, then `cd web && npm install && npm run dev` |
| Dashboard fetch 404 on /data.json | fresh clone | run `python forge sync` once to generate the files |
| Playwright install fails on old systems | glibc | fine — requests+bs4 still handles most articles |

## Health check

```bash
python forge health
```

## Reset (destroys the user's data — always ask first)

```bash
rm -rf data/ web/lib/data.json web/lib/analysis.json web/public/data.json web/public/analysis.json
```
