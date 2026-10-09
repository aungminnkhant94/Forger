# Forger Web Dashboard

A responsive web dashboard for viewing and filtering your Forger bookmarks.

## Features

- **Overview Tab**: Stats cards and recent bookmarks
- **Bookmarks Tab**: Full filtering by bucket and tags, plus search
- **Responsive Design**: Works on phone and desktop
- **No Backend**: Reads directly from JSON files

## Local Development

```bash
cd web
npm install
# Copy data files first (use --publish to see your real bookmarks locally)
python3 ../forge sync --publish
npm run dev
```

Open http://localhost:3000

## Build for Production

```bash
cd web
# Default sync leaves public JSON empty (safe for public deploys)
python3 ../forge sync
npm run build
```

Output is a Next.js build in `web/.next/` — serve with `npm run start` or deploy (see below).

## Data Source

The dashboard reads JSON files written by `forge sync`:
- `web/lib/data.json` + `web/lib/analysis.json` (private local mirror)
- `web/public/data.json` + `web/public/analysis.json` (runtime fetch)

**Publishing real bookmarks is opt-in.** By default `forge sync` writes empty
`[]` into `web/public/` so a deploy cannot leak your personal knowledge base.

```bash
# Default — public JSON empty
python3 ../forge sync

# Opt-in — copy REAL bookmarks into web/public/ for local/private viewing
python3 ../forge sync --publish
# or: FORGER_PUBLISH_DASHBOARD=1 python3 ../forge sync
```

## Personal bookmark JSON stays local

`web/public/data.json` and `web/public/analysis.json` contain URLs, page text,
notes, and tags when you opt in with `--publish` / `FORGER_PUBLISH_DASHBOARD=1`.
Do not commit them. Do not deploy a build that includes published personal JSON
unless you intentionally want that data public.

## Read-only dashboard

Remote edit/delete API routes are disabled on public Forger. Change bookmarks
with the local `forge` CLI only.

## Deployment

### Vercel Dashboard

1. Go to https://vercel.com/new
2. Import your GitHub repo
3. **Important**: Set "Root Directory" to `web`
4. Set **Build Command**: `next build`
5. Deploy

URL: your deployment URL (assigned by Vercel)

