"""Process-level configuration: where settings come from before a database.

Distinct from `application.settings`, which owns *per-repository* provider
policy stored in SQLite. Nothing in this package grants permission to do
anything; it supplies credentials and model identity only.
"""
