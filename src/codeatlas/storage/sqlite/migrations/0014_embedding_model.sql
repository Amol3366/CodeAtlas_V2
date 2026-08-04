-- Which embedding model a repository uses, as its own per-repository decision.
--
-- Until now the provider was per repository but the model was machine-wide, in
-- `.env` (ADR-0011). That made an open-source model unselectable from the
-- settings page while the OpenAI default worked out of the box: the page could
-- offer three providers and not one model.
--
-- Null means "use the configured default for the chosen provider" -- the same
-- convention `answer_model` uses one column over. That is what lets `.env` keep
-- setting a machine-wide default which a repository may override, without every
-- repository storing a copy of a value nobody chose, and it is why an existing
-- database upgrades to exactly its current behaviour.
ALTER TABLE repository_provider_policy
    ADD COLUMN embedding_model TEXT;
