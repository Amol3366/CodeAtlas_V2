-- Phase 3: resolver identity, reference round-tripping, and addressable evidence.
--
-- Additive and forward-only. Migrations 0001-0005 are applied and are not
-- edited, so the two relation columns below are added here rather than folded
-- back into 0005.

-- Resolution logic can change which edges exist without any parser changing, so
-- it needs its own invalidation handle in snapshot identity. Empty for any
-- snapshot built before resolution existed, which makes such a snapshot
-- ineligible as a reuse source rather than silently trusted.
ALTER TABLE snapshots ADD COLUMN resolver_version TEXT NOT NULL DEFAULT '';

-- A relation is a resolved reference. Storing the two fields that resolution
-- consumes but does not produce lets an unchanged file's references be
-- reconstructed from its previous relations and re-resolved, which is what makes
-- reuse and full re-resolution possible in the same run.
ALTER TABLE relations ADD COLUMN module_hint TEXT NOT NULL DEFAULT '';
ALTER TABLE relations ADD COLUMN reference_part INTEGER NOT NULL DEFAULT 0;

-- Evidence IDs are content-derived hashes and are not reversible, so an
-- addressable `GET /v1/evidence/{id}` needs them persisted.
--
-- The excerpt is deliberately NOT stored. Fetching re-reads the file from disk
-- and re-verifies the hash exactly as query-time evidence already does, so a
-- stored row can never outlive the content it describes or become a second,
-- staler source of truth about a file.
CREATE TABLE evidence (
    snapshot_id   TEXT NOT NULL
        REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    evidence_id   TEXT NOT NULL,
    file_id       TEXT NOT NULL,
    start_line    INTEGER NOT NULL,
    end_line      INTEGER NOT NULL,
    content_hash  TEXT NOT NULL,
    derivation    TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, evidence_id)
);

CREATE INDEX evidence_by_file ON evidence(snapshot_id, file_id);
