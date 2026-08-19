"""Loads query sources: ours from this directory, ``tags.scm`` from the grammar."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

_HERE = Path(__file__).parent


def load_query_source(filename: str) -> str:
    """Read a query authored in this repository."""
    return (_HERE / filename).read_text(encoding="utf-8")


def load_tags_source(module_name: str) -> str:
    """Read the ``tags.scm`` a grammar package ships.

    Nine of eleven grammars ship one; a grammar that does not cannot use this
    engine, and raising says so loudly. Returning an empty query instead would
    silently find no symbols, which is indistinguishable from a file that has
    none.
    """
    module = importlib.import_module(module_name)
    if module.__file__ is None:  # pragma: no cover - namespace package
        raise FileNotFoundError(f"{module_name} has no filesystem location")
    for root, _dirs, files in os.walk(Path(module.__file__).parent):
        if "tags.scm" in files:
            return (Path(root) / "tags.scm").read_text(encoding="utf-8")
    raise FileNotFoundError(f"{module_name} ships no tags.scm")
