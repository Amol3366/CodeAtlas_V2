-- Phase 6: the per-repository watch switch.
--
-- Additive and forward-only. Migrations 0001-0008 are applied and are not
-- edited.
--
-- `DEFAULT 1` is the load-bearing part. The product's third question is "how
-- current is that evidence?", and a watcher that stayed off until asked would
-- answer it with "stale, and you were not told". An upgrade must therefore
-- leave every existing repository watched, not quietly opted out.
--
-- The switch exists because the friendly default is not always the right one:
-- a network share or a multi-gigabyte monorepo is a legitimate reason to want
-- manual control (ADR-0007 decision 2).
--
-- Stored per repository rather than as one global setting so that disabling a
-- pathological repository does not blind the others.

ALTER TABLE repositories
    ADD COLUMN watch_enabled INTEGER NOT NULL DEFAULT 1;
