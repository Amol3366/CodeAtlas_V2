-- Which similarity space answers for a repository is a per-repository fact.
--
-- ADR-0009 decision 5 made the embedding provider a *per-repository* setting,
-- but `embedding_namespaces` kept a single global "active" row, enforced by
-- `embedding_namespaces_one_active`. The two cannot both be true. With one
-- repository on `local` (384-d) already active, a second repository opting into
-- `openai` (1536-d) got its namespace created as a *shadow*, because a shadow
-- was the only thing the index permitted. Its embeddings were then written to a
-- namespace that nothing queried: coverage was computed against the other
-- repository's namespace and read 0% forever, and every query embedded at 1536
-- dimensions and searched a 384-dimension space, which the width check rejected
-- and the caller reported as SEMANTIC_INDEX_UNAVAILABLE. Switching a single
-- repository's provider produced the same result for the same reason.
--
-- The split this migration introduces:
--
--   embedding_namespaces  -- the catalogue of similarity spaces, one row per
--                         -- (model, dimensions, normalization). Still shared,
--                         -- deliberately: content-hash embeddings are reusable
--                         -- across repositories and branches, which is the
--                         -- point of the cache.
--   repository_namespaces -- which of those spaces answers for a repository.
--
-- `status` on a namespace keeps its meaning for the migration lifecycle
-- (shadow while backfilling, retired after rollback), but it is no longer the
-- thing that decides what a query reads. ADR-0010 records this.

DROP INDEX embedding_namespaces_one_active;

CREATE TABLE repository_namespaces (
    repository_id TEXT PRIMARY KEY
                  REFERENCES repositories (repository_id) ON DELETE CASCADE,
    namespace_id  TEXT NOT NULL
                  REFERENCES embedding_namespaces (namespace_id)
                  ON DELETE RESTRICT,
    updated_at    TEXT NOT NULL
);

-- Preserve the behaviour of every database written before this migration. Any
-- repository that had opted into a provider was, by construction, being served
-- by the single active namespace -- there was no other one it could have been
-- using. Pointing it there keeps its existing vectors and coverage intact
-- rather than silently resetting them to zero on upgrade.
INSERT INTO repository_namespaces (repository_id, namespace_id, updated_at)
SELECT policy.repository_id,
       active.namespace_id,
       policy.updated_at
FROM repository_provider_policy AS policy
JOIN embedding_namespaces AS active
  ON active.status = 'active'
WHERE policy.embedding_provider <> 'none';
