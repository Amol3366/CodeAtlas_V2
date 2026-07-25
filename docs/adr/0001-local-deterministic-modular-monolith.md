# ADR-0001: Local Deterministic Modular Monolith

- Status: accepted
- Date: 2026-07-25
- Decision owners: CodeAtlas product contract
- Supersedes: none

## Context

The MVP must provide trustworthy repository intelligence on a local Windows
workstation without requiring a GPU, embedding model, LLM, cloud service, or
distributed infrastructure. CLI, REST, MCP, background jobs, and the web client
must not develop separate repository logic.

## Decision

Build a Python 3.12 modular monolith. Framework-neutral domain and application
services own repository truth. Delivery adapters call those services. SQLite
with WAL is the future MVP system of record through explicit migrations.
Deterministic scanning, parsing, Git mapping, retrieval, graph traversal,
evidence validation, and findings precede optional semantic or generative
layers. The local API binds to loopback.

Concrete storage, parser, Git, clock, ID, vector, and provider implementations
sit behind narrow interfaces only where substitution benefits tests or future
evolution. Provider integrations remain optional and repository-opt-in.

## Alternatives

- Microservices, brokers, Kubernetes, and distributed databases add operational
  and consistency risk without serving the single-user local MVP.
- PostgreSQL adds installation and recovery cost before multi-user demand.
- LLM-first retrieval cannot satisfy evidence, freshness, and deterministic
  fallback requirements.
- Cloud-first operation violates the default privacy contract.

## Consequences

The product is installable and useful without external services. All adapters
share versioned contracts and application services. SQLite contention, Windows
filesystem behavior, and process recovery must be tested directly. Future
multi-user or networked deployment requires a new ADR and migration design.

## Security and Privacy

Source remains local by default. Indexing never executes repository code.
Repository content is untrusted data. Network exposure and provider data
transfer require explicit approval and a revised threat assessment.

## Migration and Rollback

Phase 0 introduces contracts and evaluation data only. Future SQLite changes
use explicit forward migrations with tested recovery. Optional providers can be
disabled without making deterministic functions unavailable.

## Approval

Accepted by the authoritative `AGENTS.md` product contract on 2026-07-25.
