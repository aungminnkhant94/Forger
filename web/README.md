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

Static files output to `web/dist/`

## Data Source

The dashboard reads from parent directory JSON files:
- `../data/bookmarks_raw.json`
- `../data/analysis_results.json`

Run `python3 ../forge sync` from the repo root to copy them before building.

## Deployment

### Vercel Dashboard

1. Go to https://vercel.com/new
2. Import your GitHub repo
3. **Important**: Set "Root Directory" to `web`
4. Set **Build Command**: `next build`
5. Deploy

URL: your deployment URL (assigned by Vercel)

Last updated: 2026-03-22
