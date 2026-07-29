-- Phase 7: bookkeeping for the optional semantic layer (ADR-0009).
--
-- Additive and forward-only. Migrations 0001-0009 are applied and are not
-- edited. Nothing here changes existing behaviour: a build that never installs
-- the optional extras creates these tables, leaves them empty, and answers
-- exactly as Phases 0-6 did.
--
-- Three deliberate absences, each of which would be a defect if reversed:
--
-- 1. No vector column. Vectors live in the vector store; SQLite stays the
--    system of record and the vector store holds derived, rebuildable data.
-- 2. No content, prompt, excerpt, or answer column anywhere below. Section 17
--    and gate condition 6 say telemetry records counts and outcomes, never
--    content — and the cheapest way to keep that true is to leave nowhere to
--    put it.
-- 3. No opt-in row written by this migration. An upgrade must not enable a
--    provider for anyone; absence resolves to `none` in the store.

-- One similarity space. Vectors from different models, dimensions, or
-- normalization versions are not comparable (blueprint 4.7.6), so they are
-- separated here rather than being mixed and down-ranked later.
CREATE TABLE embedding_namespaces (
    namespace_id          TEXT PRIMARY KEY,
    model_id              TEXT NOT NULL,
    dimensions            INTEGER NOT NULL,
    normalization_version TEXT NOT NULL,
    -- active | shadow | retired
    status                TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    -- Null while shadow: created, possibly filling, never queried.
    activated_at          TEXT,
    UNIQUE (model_id, dimensions, normalization_version)
);

-- Exactly one namespace answers queries. A shadow namespace exists so a model
-- migration can backfill without downtime (blueprint 15.5), and the partial
-- index is what stops a half-finished cutover from leaving two spaces both
-- claiming to be current. It mirrors the one-active-snapshot rule.
CREATE UNIQUE INDEX embedding_namespaces_one_active
    ON embedding_namespaces (status)
    WHERE status = 'active';

-- The content-addressed embedding cache.
--
-- Deliberately not scoped to a snapshot or a repository: the key is derived
-- from content, so an unchanged chunk keeps its vector across snapshots and
-- branches, and a file vendored into two repositories is embedded once. That
-- reuse is the cost contract (blueprint 8.21) — a snapshot-scoped row would
-- re-embed the corpus on every index.
--
-- The cost of that choice is rows that outlive the last chunk referencing
-- their hash. Cleaning those up is a retention sweep's job (P7-04), not a
-- cascade's, because a cascade would delete vectors another repository is
-- still using.
CREATE TABLE embeddings (
    embedding_key TEXT PRIMARY KEY,
    namespace_id  TEXT NOT NULL
                  REFERENCES embedding_namespaces (namespace_id) ON DELETE CASCADE,
    content_hash  TEXT NOT NULL,
    -- pending | embedded | failed
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    embedded_at   TEXT,
    -- A code, never a provider message: messages quote payloads, and payloads
    -- are repository content.
    failure_code  TEXT
);

-- The coverage query — "which of these content hashes still need embedding" —
-- runs on every index of every repository, so it gets a covering index rather
-- than a scan of the whole cache.
CREATE INDEX embeddings_namespace_content
    ON embeddings (namespace_id, content_hash, status);

-- The privacy boundary, stored per repository because Section 4.4 draws it
-- there: content may leave the machine only for a repository the user
-- explicitly enabled. A single global switch would let one opt-in transmit a
-- different repository's source.
--
-- A repository with no row here has opted into nothing. The default therefore
-- survives a failed insert, a partial restore, and an upgrade, none of which
-- can produce a row that did not exist.
CREATE TABLE repository_provider_policy (
    repository_id        TEXT PRIMARY KEY
                         REFERENCES repositories (repository_id) ON DELETE CASCADE,
    -- none | local | openai
    embedding_provider   TEXT NOT NULL,
    -- Null means unlimited, which the application layer permits only for a
    -- provider that does not transmit.
    monthly_token_budget INTEGER,
    per_run_token_budget INTEGER,
    updated_at           TEXT NOT NULL
);

-- Provider usage, reduced to what can be counted. Budgets are enforced from
-- this table, and a support question about cost is answered from it, without
-- any of it being able to record what was sent.
CREATE TABLE provider_usage (
    usage_id      TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL
                  REFERENCES repositories (repository_id) ON DELETE CASCADE,
    operation     TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model_id      TEXT NOT NULL,
    request_count INTEGER NOT NULL,
    token_count   INTEGER NOT NULL,
    latency_ms    INTEGER NOT NULL,
    outcome       TEXT NOT NULL,
    occurred_at   TEXT NOT NULL
);

-- Budget checks ask "how many tokens since this instant, for this repository",
-- which is this index exactly.
CREATE INDEX provider_usage_repository_time
    ON provider_usage (repository_id, occurred_at);
