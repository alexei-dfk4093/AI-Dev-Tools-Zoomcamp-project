# EcoMind — AI Agent Operating Instructions

## Documentation Map

Read the rules below, then open the document that matches the task. Nested
AGENTS.md files govern their layer; this root file must not duplicate them.

| Document | Scope |
|----------|-------|
| [`backend/AGENTS.md`](backend/AGENTS.md) | Backend: APIs, business logic, data access, news ingestion, provider integrations. |
| [`frontend/AGENTS.md`](frontend/AGENTS.md) | Frontend: pages, market-terminal visual identity, interaction rules. |
| [`agents/AGENTS.md`](agents/AGENTS.md) | In-product analyst behavior: source attribution, facts vs interpretation, answer rules. |
| [`docs/product-spec.md`](docs/product-spec.md) | What EcoMind should do: capabilities, phased requirements, integrity and quality requirements, objective-to-tracker mapping. |
| [`docs/agent-team.md`](docs/agent-team.md) | Agent roles, responsibilities, and the collaboration process. |
| [`backend/README.md`](backend/README.md) / [`frontend/README.md`](frontend/README.md) | Setup, configuration, and startup. |
| [`project requirements.md`](project%20requirements.md) | Zoomcamp objectives, status, and verification evidence. |

Work items are tracked in the public
[GitHub issue tracker](https://github.com/alexei-dfk4093/AI-Dev-Tools-Zoomcamp-project/issues).

## 1. Project Overview

EcoMind is a multi-LLM financial intelligence platform designed for traders, investors, and financial researchers.

The platform collects economic and financial news from external sources, processes and categorizes the information, and uses multiple Large Language Models (LLMs) to analyze financial events from different analytical perspectives.

Users should be able to:

- Explore economic and financial news.
- Read AI-generated analyses of financial events.
- Compare different LLM providers.
- Select analytical personalities: Optimistic, Neutral, and Cautious.
- Discuss financial events with individual AI analysts.
- Allow multiple AI analysts to debate and challenge each other's conclusions.
- Explore potential market implications.
- Review historical analyses and evaluate their performance.

## 2. Primary Engineering Objectives

The AI coding agent must prioritize:

1. Correctness over implementation speed.
2. Maintainability over unnecessary complexity.
3. Modular architecture and separation of concerns.
4. Reusability of components and services.
5. Security and proper handling of external integrations.
6. Automated testing and validation.
7. Clear documentation.
8. Consistent user experience.

## 3. General Development Rules

### 3.1 Understand Before Implementing

Before modifying code, the agent must:

- Inspect the relevant project structure.
- Read the root AGENTS.md and applicable nested AGENTS.md files.
- Understand existing implementations and dependencies.
- Identify affected modules and integration points.
- Avoid duplicating existing functionality.

Do not assume that a feature does not exist without inspecting the repository.

### 3.2 Planning

For complex tasks:

1. Understand the requested functionality.
2. Identify affected components.
3. Propose an implementation plan.
4. Identify potential dependencies and risks.
5. Implement incrementally.
6. Run relevant tests.
7. Summarize the changes.

Do not create lengthy plans for trivial changes.

### 3.3 Code Quality

- Follow existing project conventions.
- Use descriptive variable, function, and class names.
- Prefer small, focused functions.
- Avoid unnecessary code duplication.
- Avoid oversized modules.
- Use appropriate type annotations.
- Handle errors explicitly.
- Avoid unnecessary abstractions.
- Do not introduce dependencies without a clear justification.
- but you can break this laws when you really need to 
- if you needed to break the laws you must mention you did

### 3.4 Architecture

Maintain clear boundaries between:

- Frontend presentation.
- Backend API and business logic.
- News ingestion and preprocessing.
- LLM providers and orchestration.
- Database operations.
- Evaluation and testing.
- Infrastructure and deployment.

Business logic must not be unnecessarily duplicated across layers.

### 3.5 Dependencies

Before adding a dependency:

- Check whether an existing dependency already provides the functionality.
- Consider its maintenance status and compatibility.
- Explain why the dependency is necessary.
- Avoid adding large frameworks for simple tasks.

Do not silently replace existing dependencies or major technologies.

### 3.6 Configuration and Secrets

- Store credentials in environment variables.
- Maintain an appropriate `.env.example`.
- Never commit actual API keys or secrets.
- Validate required configuration at application startup.
- Never expose private API credentials to the frontend.

### 3.7 Error Handling

- Handle external API failures.
- Handle timeouts and rate limits.
- Provide meaningful error messages.
- Avoid silently swallowing exceptions.
- Implement retries only where appropriate.
- Ensure one failed LLM provider does not unnecessarily break other providers.

### 3.8 Documentation

Update documentation when changing:

- Public APIs.
- Database schemas.
- Configuration.
- Architecture.
- Installation procedures.
- External integrations.

### 3.9 Git and Existing Work

- Do not overwrite unrelated user changes.
- Do not reset or delete files without explicit authorization.
- Do not commit changes unless requested.
- Keep changes focused on the requested task.

## 4. Product Requirements

The project should be developed incrementally. The authoritative capability
list and phased requirements (Phases 1–5) live in
[`docs/product-spec.md`](docs/product-spec.md) — §3 current capabilities and
§4 planned phases. Consult them before scoping any task.

Do not implement future-phase functionality unless it is explicitly requested or necessary for the current task.

## 5. Financial Information Integrity

This is a critical project requirement.

- Never invent financial news or economic data.
- Distinguish actual reported facts from AI-generated interpretations.
- Preserve original publication timestamps.
- Identify the original news source.
- Provide traceable references for important claims.
- Do not represent hypothetical scenarios as actual events.
- Do not present model confidence as statistical certainty.
- Do not describe an analytical opinion as a guaranteed market prediction.
- Avoid misleading directional conclusions.

## 6. LLM Architecture Requirements

Keep LLM providers independent of analytical personalities.

Provider examples:

- deepseek 
- GLM
- free openai model

Analytical personalities:

- Optimistic
- Neutral
- Cautious

The system must allow different personalities to operate with different providers without duplicating the provider integration code.

All analysts should receive equivalent underlying evidence when their outputs are compared.

In-product analyst behavior (answer rules, attribution, uncertainty labeling) is defined in [`agents/AGENTS.md`](agents/AGENTS.md).

## 7. Definition of Done

A task is not considered complete merely because code was generated.

Before reporting completion:

- Verify that the implementation matches the requested behavior.
- Run relevant tests.
- Check affected integrations.
- Validate types and schemas where applicable.
- Check for obvious regressions.
- Update relevant documentation.
- Report any incomplete work or known limitations.

Never claim that a test passed if it was not actually executed.

## 8. Agent Communication

At the end of each significant task, provide:

1. Summary of implemented changes.
2. Files created or modified.
3. Important architectural decisions.
4. Tests executed and their results.
5. Known limitations.
6. Recommended next steps.

If a requirement is ambiguous and could materially affect architecture, ask for clarification before making an irreversible decision.

The agent should act as a careful software engineering collaborator, not an autonomous architect making uncontrolled changes.