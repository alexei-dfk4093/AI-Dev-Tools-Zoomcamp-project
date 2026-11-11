# EcoMind frontend

React + TypeScript + Vite client for EcoMind, a financial news brief with
source-grounded AI summaries and per-headline discussions.

The visual direction is a **dark market terminal** identity (see
`AGENTS.md` §12): near-black surfaces, hairline-separated story rows,
oversized IBM Plex Mono numerals, Archivo headings, and a single terminal-red
accent (#ef5350).

## Pages

- **News feed (`/`)** — paginated economics headlines loaded from
  `GET /api/v1/news`. Each headline links to its discussion page; the ↗
  marker opens the original publisher article.
- **Discussion (`/discussion?article=…`)** — chat with the selected OpenRouter
  model about one headline, with article-specific market context, related
  companies and markets, and suggested questions from
  `GET /api/v1/news/{id}/insights`.

The article payload is embedded in the discussion URL so the page can be
refreshed or shared without persisting client state.

## Development

```powershell
npm install
npm run dev
```

The Vite dev server proxies `/api` requests to the FastAPI backend
(`http://127.0.0.1:8000`), which must be running with a configured `.env`
(see `../backend/README.md` and `../.env.example`).

## Verification

```powershell
npm run lint     # oxlint
npm run test     # vitest unit tests (src/*.test.ts)
npm run build    # tsc -b && vite build
```
