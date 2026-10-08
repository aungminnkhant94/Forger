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
# Copy data files first
python3 ../forge sync
npm run dev
```

Open http://localhost:3000

## Build for Production

```bash
cd web
python3 ../forge sync
npm run build
```

Output is a Next.js build in `web/.next/` — serve with `npm run start` or deploy (see below).

## Data Source

The dashboard reads JSON files written by `forge sync`:
- `web/lib/data.json` + `web/lib/analysis.json` (build-time)
- `web/public/data.json` + `web/public/analysis.json` (runtime fetch)

Run `python3 ../forge sync` from the repo root to copy them before building.


## Personal bookmark JSON stays local

`web/public/data.json` and `web/public/analysis.json` are copies of your bookmarks (URLs, page text, notes, tags). They are for local `npm run dev` only. Do not commit them and do not deploy them — `forge sync` must not publish `web/public/data.json`.

## Deployment

### Vercel Dashboard

1. Go to https://vercel.com/new
2. Import your GitHub repo
3. **Important**: Set "Root Directory" to `web`
4. Set **Build Command**: `next build`
5. Deploy

URL: your deployment URL (assigned by Vercel)

