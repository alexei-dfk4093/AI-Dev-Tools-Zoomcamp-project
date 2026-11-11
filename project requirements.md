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
   storage end to end; provide one-command local startup. **Partial:** all
   layers exist, but startup currently needs separate commands.
6. **Testing (2 pts)** — Add/verify unit and integration tests runnable with
   one command. **Partial:** test files exist; unified run and integration
   coverage need verification.
7. **Containerization (2 pts)** — Run the complete application and persistent
   data with one Docker Compose command. **Not started:** no Docker setup found.
8. **Deployment (2 pts)** — Publish a working deployment or clear demo.
   **Not started:** no deployment found.
9. **CI/CD (up to 3 pts)** — Run tests on pull requests, deploy automatically
   to development, and gate production deployment manually. **Not started:**
   no CI workflow found.
10. **Observability (2 pts)** — Provide a UI for correlated logs, metrics,
    and traces for a user journey, without sensitive data. **Partial:** logs
    exist; correlated telemetry and UI do not.
11. **User-impact alerts (1 pt)** — Configure and safely test at least one
    actionable alert. **Not started.**
12. **On-call agent (2 pts)** — Have an agent investigate alerts and verify
    fixes, with human approval for production-impacting actions. **Not
    started.**

**Order:** 1–6, then 7–8, then 9–12. Record brief verification evidence here
as each objective is completed. Current score: **8/24 verified**.
