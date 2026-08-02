-- Answer generation is a second, independent provider decision.
--
-- Separate columns rather than reusing `embedding_provider`, because the two
-- choices are genuinely independent: a repository can retrieve with local
-- embeddings and answer with OpenAI, or embed with OpenAI and not generate at
-- all. Folding them into one column would make "which provider" ambiguous at
-- every read site, and the transmit question has to be answerable for each
-- decision separately.
--
-- Every column is defaulted or nullable, so an existing database upgrades to
-- exactly its current behaviour: no answer provider, therefore no generation,
-- therefore nothing transmitted that was not transmitted before.

ALTER TABLE repository_provider_policy
    ADD COLUMN answer_provider TEXT NOT NULL DEFAULT 'none';

-- Null means "use the configured default for the chosen provider". That is what
-- lets `.env` set a machine-wide default which the settings page overrides per
-- repository, without every repository storing a copy of a value nobody chose.
ALTER TABLE repository_provider_policy
    ADD COLUMN answer_model TEXT;

-- Null means the built-in bound. A heavier local model legitimately needs
-- longer than a 3B default: a timeout tuned to the small model would turn
-- "use a bigger model for deeper reasoning" into a timeout on every question,
-- which looks exactly like the feature being broken.
ALTER TABLE repository_provider_policy
    ADD COLUMN answer_timeout_seconds INTEGER;
