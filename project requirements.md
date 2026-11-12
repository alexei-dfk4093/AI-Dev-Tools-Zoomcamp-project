# AI Dev Tools Zoomcamp — Project Objectives

Complete these objectives one at a time. Mark each done only after its result
is verified. Scoring follows the Zoomcamp rubric (24 points total).

1. **Problem description (2 pts)** — Root [README](README.md) explains the
   problem, key capabilities, expected behavior, and financial-information
   caveat. **Done:** verified — README has problem, "How EcoMind helps",
   "Expected behavior", and "What EcoMind is not" sections.
2. **Product specification and public tracker (2 pts)** — Write down what the
   product should do, then put the work items in a public tracker (for example,
   GitHub Issues) so others can see the tasks and how each will be checked.
   **Done:** specification in [docs/product-spec.md](docs/product-spec.md);
   tracker is public GitHub Issues (12 objective issues, #3–#14, each with
   work item and check) linked from the README; public access verified via
   unauthenticated API request.
3. **Agent team (2 pts)** — Define agent roles, responsibilities, and
   collaboration process. **Done:** roles, responsibilities, and
   collaboration process documented in [docs/agent-team.md](docs/agent-team.md).
4. **Context management (2 pts)** — Make root AGENTS.md point to modular
   project and process docs. **Done:** verified — root AGENTS.md has a
   documentation map referencing `backend/AGENTS.md`, `frontend/AGENTS.md`,
   `agents/AGENTS.md`, `docs/product-spec.md`, `docs/agent-team.md`, setup
   READMEs, and the tracker; the duplicated phase list was replaced with a
   pointer to the product spec.
5. **Working application (2 pts)** — Verify frontend, backend, and persistent
   storage end to end; provide one-command local startup. **Done:** verified
   2026-11-11 — `.\start.ps1` from the root starts backend (uvicorn + SQLite),
   waits for `/health`, starts the Vite frontend, and opens the app;
   live check: `/health` ok, `/api/v1/news/status` reported 273 persisted
   articles (provider refresh recorded), feed served with publisher/timestamp,
   frontend served and `/api` proxied to the backend, free-model list returned.
   **Feed reliability repaired and re-verified 2026-11-12:** a stale-cache feed
   read hung 5–7 minutes when AI summaries were missing (inline provider
   refresh + summarization on the read path). Fixes: provider results and
   `provider_state` are stored immediately and enrichment/summarization moved
   to non-blocking single-flight background tasks with retry backoff; summary
   batches now share the daily AI request budget through `openrouter.py`
   (a 429 pauses AI calls instead of spiraling); publisher summaries are
   final and never re-requested; robots.txt is cached per host with a
   failure TTL and no redirect-following. Live verification: plain feed read
   200 ms, `refresh=true` returned cached articles during a provider outage,
   one 429 paused all AI calls (no further provider POSTs in the log).
6. **Testing (2 pts)** — Add/verify unit and integration tests runnable with
   one command. **Done:** verified 2026-11-12 — `.\run-tests.ps1` runs backend
   pytest (79 tests, incl. full-stack `backend/tests/test_integration.py`:
   provider HTTP → SQLite → API with mocked externals, plus new tests for the
   non-blocking feed read, summary backoff, publisher-summary finality,
   provider-state ordering, the shared AI request budget, and robots.txt
   caching) and frontend vitest (19 tests) in one command, all passing.
7. **Containerization (2 pts)** — Run the complete application and persistent
   data with one Docker Compose command. **Done:** verified 2026-11-12 —
   `backend/Dockerfile` (python:3.14-slim, SQLite on the `/app/data` volume),
   `frontend/Dockerfile` (node:26-alpine build → nginx:1.29-alpine with `/api`
   proxied to the backend), `frontend/nginx.conf`, root `docker-compose.yml`
   (env from `.env` when present, `backend-data` volume, healthcheck-gated
   frontend start). `docker compose up --build` verified: backend healthy,
   prefetch persisted 60 articles, enrichment ran, feed served through nginx
   (200 OK, 20 articles), SPA shell served at :8080.
8. **Deployment (2 pts)** — Publish a working deployment or clear demo.
   **Done:** verified 2026-11-12 — the development deployment workflow
   publishes backend and frontend images to GHCR on every push to `main`
   (`ghcr.io/alexei-dfk4093/ecomind-{backend,frontend}:main`, pinned commit
   SHA tags too); `docker-compose.ghcr.yml` runs the published images with
   one command (`docker compose -f docker-compose.ghcr.yml up -d`), and the
   README documents it. First publish verified: run
   [#43242692141](https://github.com/alexei-dfk4093/AI-Dev-Tools-Zoomcamp-project/actions/runs/43242692141)
   — test gate passed, both `docker/build-push-action` steps succeeded.
9. **CI/CD (up to 3 pts)** — Run tests on pull requests, deploy automatically
   to development, and gate production deployment manually. **Done:**
   verified 2026-11-12 — `.github/workflows/tests.yml` runs backend pytest +
   frontend vitest + production build on PRs and pushes (reusable deploy
   gate); `deploy-development.yml` gates GHCR publishing on the test suite
   for every push to `main`; `deploy-production.yml` is a manual
   `workflow_dispatch` with a confirm input and the `production` environment
   gate. First runs (commit 7482cbc): Tests
   [#43242692064](https://github.com/alexei-dfk4093/AI-Dev-Tools-Zoomcamp-project/actions/runs/43242692064)
   and Development deployment
   [#43242692141](https://github.com/alexei-dfk4093/AI-Dev-Tools-Zoomcamp-project/actions/runs/43242692141)
   both green (an initial failure exposed a CI-only startup-config gap in
   the tests, fixed by giving the suite a deterministic environment instead
   of relying on a developer's `.env`).
10. **Observability (2 pts)** — Provide a UI for correlated logs, metrics,
    and traces for a user journey, without sensitive data. **Partial:** logs
    exist; correlated telemetry and UI do not.
11. **User-impact alerts (1 pt)** — Configure and safely test at least one
    actionable alert. **Not started.**
12. **On-call agent (2 pts)** — Have an agent investigate alerts and verify
    fixes, with human approval for production-impacting actions. **Not
    started.**

**Order:** 1–6, then 7–8, then 9–12. Record brief verification evidence here
as each objective is completed. Current score: **19/24 verified**
(objectives 1–9; remaining: observability, user-impact alerts, on-call
agent).
