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

See [backend setup](backend/README.md) and
[frontend setup](frontend/README.md) for requirements, configuration, and
startup instructions. API health and interactive documentation are available
at `/health` and `/docs` when the backend is running.
