# EcoMind — Product specification

EcoMind turns economic news into a source-linked reading and analysis
workflow. This document states what the product should do, what it must not
do, and how each piece of work is checked. Work items and their acceptance
checks live in the public tracker:
[AI-Dev-Tools-Zoomcamp-project — Issues](https://github.com/alexei-dfk4093/AI-Dev-Tools-Zoomcamp-project/issues).

## 1. Problem

Economic news is published across many outlets, while headlines and short
summaries often leave readers without enough context to assess a
development. It is also difficult to separate what a source actually
reported from what an AI system inferred. EcoMind gives readers a focused
feed, the full reporting context per story, and AI analysis that stays
attached to its source.

## 2. Who it is for

Traders, investors, and financial researchers who need to read economic
news with context, compare AI readings of the same event, and keep the
original reporting visible at every step.

## 3. Current capabilities

1. **Focused feed** — a filtered economics and market-news feed; only
   economics intelligence is served, with each story's publisher,
   publication time, and original link visible.
2. **Read with context** — each story keeps its summary grounded in the
   publisher's own page: the article text is retrieved from the publisher
   (JSON-LD, `<article>`/`<main>`, CMS containers), and the summary adds
   concrete reported details instead of restating the headline.
3. **Explore implications** — per-article analysis returns the companies
   and traded symbols connected to the story (suppliers, customers,
   competitors, lenders, sector peers, labelled as named or potential
   exposure), the directional effect the article reports (positive,
   neutral, negative) with its stated reasons, and suggested questions
   derived from the article's own content.
4. **Ask follow-ups** — a discussion tied to one story. The assistant may
   fetch the publisher's page (domain-restricted) and search the wider web
   to corroborate the event; every web finding is attributed to its source,
   and the reader is told when a page could not be read or sources
   disagree.
5. **Model choice** — free OpenRouter models are selectable for the
   discussion composer (`GET /api/v1/discussions/models`); paid model IDs
   are ignored.

## 4. Planned capabilities (phases)

Ordered; later phases are not implemented until earlier ones are verified.

- **Phase 1 — News aggregation**: collect financial news from permitted
  sources, normalize metadata, store in the database, categorize, detect
  duplicates, associate articles with underlying financial events.
- **Phase 2 — Multi-LLM analysis**: integrate multiple LLM providers
  independently, run models separately, support the three analytical
  personalities (Optimistic, Neutral, Cautious), standardize outputs,
  preserve source references, isolate provider failures.
- **Phase 3 — AI discussion**: individual analyst conversations with
  context, optional multi-agent debates, analysts challenging claims and
  assumptions, facts distinguished from interpretations.
- **Phase 4 — Market impact**: associate events with relevant assets,
  integrate market data, analyze short- and long-term implications, track
  subsequent market movements.
- **Phase 5 — Evaluation**: evaluate factual accuracy, source attribution,
  reasoning quality, latency and API costs, historical analytical
  outcomes, reproducible evaluations.

## 5. Expected behavior

- The feed loads with publisher, publication time, and original link
  visible; provider lag is shown, not hidden.
- AI output is marked as AI and stays separate from the publisher's
  reporting.
- Follow-up answers address the question asked and name their sources.
- When AI is unconfigured or unavailable, the app shows an explicit
  configuration or availability error instead of placeholder content.

## 6. What EcoMind must not do

These constraints apply to every phase and every component.

- Never invent financial news or economic data.
- Never represent AI-generated interpretation as reported fact, or
  hypothetical scenarios as actual events.
- Preserve original publication timestamps and identify the original news
  source.
- Provide traceable references for important claims.
- Never present model confidence as statistical certainty, an analytical
  opinion as a guaranteed prediction, or a directional reading as certain.
- Not provide personalized investment advice.

## 7. Architecture and quality requirements

- **Stack**: React + TypeScript frontend, FastAPI backend, SQLite for
  cached news and analysis, OpenRouter for AI analysis and discussion.
- **Layer boundaries**: frontend presentation; backend API and business
  logic; news ingestion and preprocessing; LLM providers and orchestration;
  database operations; evaluation; infrastructure. Business logic is not
  duplicated across layers.
- **LLM architecture**: providers are independent of analytical
  personalities; example providers are deepseek, GLM, and free OpenAI
  models via OpenRouter. Personalities (Optimistic, Neutral, Cautious) must
  run over interchangeable providers without duplicating provider
  integration code, and compared analysts must receive equivalent
  underlying evidence.
- **Security**: credentials only in environment variables with an
  up-to-date `.env.example`; no real keys committed; configuration
  validated at startup; no provider credentials exposed to the frontend.
- **Reliability**: external API failures, timeouts, and rate limits are
  handled explicitly; one failed LLM provider never breaks other providers;
  failures are never silently swallowed.
- **Testing**: unit and integration tests with mocked external APIs;
  deterministic and runnable with one command.

## 8. Work items and acceptance checks

The public tracker holds one issue per objective; each issue states the
work item and how it will be checked.

| Objective | Issue | How it is checked |
|-----------|-------|-------------------|
| 1. Problem description | #3 | Root README explains the problem, key capabilities, expected behavior, and the financial-information caveat |
| 2. Product specification and public tracker | #13 | This specification exists and the tracker is public with one issue per objective, each stating the check |
| 3. Agent team | #14 | Agent roles, responsibilities, and collaboration process are documented |
| 4. Context management | #4 | Root AGENTS.md points to modular project and process docs |
| 5. Working application | #5 | One-command local startup verified end to end (frontend, backend, storage) |
| 6. Testing | #6 | Unit and integration tests run with one command |
| 7. Containerization | #7 | Docker Compose runs the complete application with persistent data |
| 8. Deployment | #8 | A working deployment is published or a clear demo provided |
| 9. CI/CD | #9 | Tests run on PRs; development deploys automatically; production is gated manually |
| 10. Observability | #10 | Correlated logs, metrics, and traces UI for a user journey, without sensitive data |
| 11. User-impact alerts | #11 | At least one actionable alert is configured and safely tested |
| 12. On-call agent | #12 | An agent investigates alerts and verifies fixes, with human approval for production-impacting actions |

Scoring follows the Zoomcamp rubric (24 points total); verified progress is
recorded in [`project requirements.md`](../project%20requirements.md).
