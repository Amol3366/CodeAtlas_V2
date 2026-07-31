-- Phase 7 P7-09: shadow embedding model migrations.
--
-- Namespaces hold similarity spaces; this table holds the user-visible
-- operation that moves one repository from one namespace to another. It stores
-- IDs, states, timestamps, and failure codes only. No source, prompt, excerpt,
-- answer, vector, or provider message can fit here.

CREATE TABLE embedding_migrations (
    migration_id        TEXT PRIMARY KEY,
    repository_id       TEXT NOT NULL
                        REFERENCES repositories (repository_id) ON DELETE CASCADE,
    source_namespace_id TEXT NOT NULL
                        REFERENCES embedding_namespaces (namespace_id)
                        ON DELETE RESTRICT,
    target_namespace_id TEXT NOT NULL
                        REFERENCES embedding_namespaces (namespace_id)
                        ON DELETE CASCADE,
    -- backfilling | ready_for_cutover | active | rolled_back | failed
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    activated_at        TEXT,
    rolled_back_at      TEXT,
    -- A code, never a provider/vector-store message.
    failure_code        TEXT,
    UNIQUE (repository_id, source_namespace_id, target_namespace_id)
);

CREATE INDEX embedding_migrations_repository
    ON embedding_migrations (repository_id, created_at);
