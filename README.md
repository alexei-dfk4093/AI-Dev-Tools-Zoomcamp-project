# EcoMind

**EcoMind turns economic news into a source-linked reading and analysis
workflow.** Readers can scan a focused feed, open a story, understand what the
article reports, and ask follow-up questions without losing sight of the
original source.

## The problem

Economic news is published across many outlets, while headlines and short
summaries often leave readers without enough context to assess a development.
It can also be difficult to separate what a source actually reported from
what an AI system inferred.

## How EcoMind helps

1. **Find relevant stories** in a filtered economics and market-news feed.
2. **Read with context:** each story keeps its publisher, publication time,
   and original link alongside its summary and article-specific analysis.
3. **Explore implications:** review related companies and markets, the effect
   reported by the article, and questions derived from its content.
4. **Ask follow-ups** in a discussion tied to that story.

The application uses a React frontend, FastAPI backend, and SQLite for cached
news and analysis. OpenRouter powers AI analysis and discussion when
configured.

## Expected behavior

- The feed lists economics and market stories with publisher, publication
  time, and the original link visible; provider lag is shown, not hidden.
- Each story explains what the article reports before adding AI analysis,
  and the AI part stays clearly separate from the source's reporting.
- Follow-up answers address the question asked, name their sources, and say
  when a page could not be read or when sources disagree.
- When AI is unconfigured or unavailable, the app shows an explicit
  configuration or availability error instead of placeholder content.

## What EcoMind is not

AI output is interpretation, not a substitute for the publisher's reporting.
EcoMind does not guarantee factual completeness or predict market prices, and
its analysis is not personalized investment advice. Provider access, article
availability, and AI output can vary.

## Public tracker

The work items and Zoomcamp objectives are tracked in the public GitHub
issue tracker:

[AI-Dev-Tools-Zoomcamp-project — Issues](https://github.com/alexei-dfk4093/AI-Dev-Tools-Zoomcamp-project/issues)

The tracker holds one issue per project objective, each describing the work
item and how it will be checked:

1. Problem description
2. Product specification and public tracker
3. Agent team
4. Context management
5. Working application
6. Testing
7. Containerization
8. Deployment
9. CI/CD
10. Observability
11. User-impact alerts
12. On-call agent

## Documentation

- [Product specification](docs/product-spec.md) — what EcoMind should do,
  planned capabilities, and how each objective is checked.
- [Agent team](docs/agent-team.md) — agent roles, responsibilities, and
  collaboration process.
- Backend and frontend setup guides: [backend](backend/README.md),
  [frontend](frontend/README.md).

## Run locally

One command starts the complete application — FastAPI backend, SQLite
persistent storage, and the React frontend:

```powershell
.\start.ps1
```

The script creates the Python virtual environment and installs frontend
dependencies on first run, waits until the API is healthy, then serves the
app at <http://localhost:5173> (API docs at
<http://127.0.0.1:8000/docs>). Configuration is read from the project-root
`.env` file (see [backend setup](backend/README.md)). Press Ctrl+C to stop
both servers.

To run the same pieces manually instead:

- Backend: see [backend setup](backend/README.md) (`uvicorn` command).
- Frontend: `npm run dev` from `frontend` (see
  [frontend setup](frontend/README.md)).

API health and interactive documentation are available at `/health` and
`/docs` when the backend is running.

## Run with Docker

The full stack runs in containers — backend (FastAPI + SQLite) and frontend
(nginx-served static build with `/api` proxied to the backend):

```powershell
docker compose up --build
```

- Frontend: <http://localhost:8080>
- API docs: <http://127.0.0.1:8000/docs>

Configuration comes from the project-root `.env` file when present (copy
`.env.example`); without keys the app runs with publisher descriptions and
explicit configuration errors instead of AI output. The SQLite database
persists in the `backend-data` volume across container replacements.
`docker compose down --volumes` stops and clears the stored data.

### Run the published images

The development deployment workflow publishes ready-to-run images to GHCR on
every push to `main`. To run EcoMind without building anything:

```powershell
docker compose -f docker-compose.ghcr.yml up -d
```

This pulls `ghcr.io/alexei-dfk4093/ecomind-backend:main` and
`ghcr.io/alexei-dfk4093/ecomind-frontend:main` (pin a commit by replacing
`main` with a commit SHA) and starts the same stack.

## CI/CD

GitHub Actions workflows live in `.github/workflows`:

- **Tests** (`tests.yml`) — backend pytest and frontend vitest plus the
  production frontend build, on every pull request and push to `main`.
  The deploy workflows call it as a gate before publishing.
- **Development deployment** (`deploy-development.yml`) — on every push to
  `main`, after tests pass, builds and publishes backend and frontend
  images to GHCR (`ghcr.io/alexei-dfk4093/ecomind-{backend,frontend}:main`).
- **Production deployment** (`deploy-production.yml`) — manual run from the
  Actions tab with an explicit confirmation input and the `production`
  environment gate; publishes `:prod` image tags after tests pass.

## Tests

One command runs the backend and frontend test suites (external APIs are
mocked, so the run is deterministic):

```powershell
.\run-tests.ps1
```

Individual suites: `python -m pytest backend\tests` (backend) and
`npm run test` from `frontend` (frontend).
