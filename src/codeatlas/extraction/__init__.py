"""Reference extraction: what a file says, before anything else is consulted.

Extraction is deliberately separate from resolution. Everything in this package
is a pure function of one file's bytes, which is what makes an unchanged file's
references reusable across snapshots. Deciding what a reference *means* needs
the whole snapshot and lives in ``resolution``.
"""
