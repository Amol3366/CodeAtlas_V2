# Non-Goals — accepted & signed off (Phase 0)

CodeAtlas is **NOT** (CLAUDE.md §1, Blueprint §1.4, §6.4):

- another AI IDE or "chat with your codebase" product;
- an autonomous code editor / autonomous code modification;
- a cloud service (it is local-first, single-user, Windows-first);
- dependent on embeddings or an LLM for core operation.

## Deferred scope (not in the first usable release)

- a complete alternative IDE; a rich Monaco-based editing environment;
- automatic merge approval / automatic pull-request comments;
- GitHub App or GitLab App integration; cloud agents;
- multi-user accounts, multi-tenant infrastructure, enterprise SSO;
- organization-wide multi-repository graphs;
- mandatory external LLM calls; mandatory vector search;
- microservices, Kubernetes, Docker-as-a-requirement;
- perfect runtime call-graph generation; full binary analysis;
- full PDF/OCR processing;
- broad-but-shallow support for many programming languages;
- CI test execution; **behavioral coverage claims**.

## MVP non-goals (Blueprint §6.4)

- replacing Cursor, Copilot, VS Code, or JetBrains;
- complete codebase chat as the primary workflow;
- cloud deployment; multiple users;
- perfect dynamic call resolution;
- organization-wide search.

## Hard invariants these protect

- **Deterministic before semantic** — everything works with `NoEmbeddingProvider`
  and `NoAnswerProvider`.
- **Never execute repository code** during scan/parse/index.
- **Transparent uncertainty** — `CALLS` (static_resolved) vs `MAY_CALL`
  (heuristic) is sacred; never claim behavioral coverage without execution.
- **Modular monolith** — no Celery/Redis/RabbitMQ/Postgres/Neo4j/Qdrant/K8s.

---

**Sign-off:** Accepted for the CodeAtlas MVP on 2026-07-22. Any change to this
list requires updating CLAUDE.md §2 invariants and Blueprint §1.4 in the same
change.
