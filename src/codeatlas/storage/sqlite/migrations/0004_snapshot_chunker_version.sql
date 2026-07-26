-- Phase 2: record which chunker built a snapshot's chunks.
--
-- Reuse copies chunk rows from the previous active snapshot instead of
-- recomputing them. That is only sound when the chunker that produced those
-- rows is the one running now, so the version has to be stored rather than
-- inferred. The default is empty on purpose: a snapshot created before this
-- column existed has no chunks, so it can never be a reuse source.

ALTER TABLE snapshots ADD COLUMN chunker_version TEXT NOT NULL DEFAULT '';
