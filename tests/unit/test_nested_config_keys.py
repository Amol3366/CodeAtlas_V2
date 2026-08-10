"""A nested configuration key is addressable, and cites the line that sets it.

`_nested_paths` has always computed the dotted paths; they were flattened into a
display string and never became symbols, so "what port is configured" could only
ever answer `service` and nothing could cite the assignment (ADR-0025).
"""

from __future__ import annotations

from codeatlas.contracts import SymbolKind
from codeatlas.domain.ids import file_id
from codeatlas.parsing.document_parser import DocumentParser
from codeatlas.parsing.registry import ParseRequest

YAML = b"service:\n  name: sample\n  port: 8080\nfeatures:\n  audit: true\n"
TOML = b'[server]\nhost = "127.0.0.1"\nport = 8080\ndebug = false\n'
JSON = b'{\n  "name": "sample",\n  "scripts": {\n    "test": "never-run"\n  }\n}\n'


def _request(content: bytes, relative_path: str, language: str) -> ParseRequest:
    return ParseRequest(
        repository_id="repo_1",
        snapshot_id="snap_1",
        file_id=file_id("repo_1", relative_path),
        relative_path=relative_path,
        language=language,
        content=content,
    )


def _keys(content: bytes, path: str, language: str) -> dict[str, tuple[int, int]]:
    result = DocumentParser().parse(_request(content, path, language))
    return {
        symbol.qualified_name: (symbol.start_line, symbol.end_line)
        for symbol in result.symbols
        if symbol.kind is SymbolKind.CONFIG_KEY
    }


def test_a_yaml_leaf_is_addressable_and_cites_its_own_line() -> None:
    keys = _keys(YAML, "config/settings.yaml", "yaml")

    assert "service.port" in keys
    assert keys["service.port"] == (3, 3)
    assert "features.audit" in keys
    assert keys["features.audit"] == (5, 5)


def test_a_toml_leaf_is_addressable_and_cites_its_own_line() -> None:
    keys = _keys(TOML, "app.toml", "toml")

    assert keys["server.host"] == (2, 2)
    assert keys["server.port"] == (3, 3)


def test_a_json_leaf_is_addressable_and_cites_its_own_line() -> None:
    keys = _keys(JSON, "package.json", "json")

    assert keys["scripts.test"] == (4, 4)


def test_the_parent_key_is_still_addressable() -> None:
    """Nesting adds symbols; it must not remove the one that already worked."""
    keys = _keys(YAML, "config/settings.yaml", "yaml")

    assert "service" in keys
    assert keys["service"][0] == 1


def test_the_same_leaf_name_under_two_parents_gets_two_lines() -> None:
    """`port` appears twice. Each path must cite its own occurrence.

    The leaf line is found by searching inside the parent's block, so two blocks
    that both contain `port` are distinguished by where the search starts. If
    they collapsed onto one line, one of the two citations would point a reader
    at the wrong file position while claiming to be evidence.
    """
    content = b"service:\n  port: 8080\nadmin:\n  port: 9090\n"
    keys = _keys(content, "config/two.yaml", "yaml")

    assert keys["service.port"] == (2, 2)
    assert keys["admin.port"] == (4, 4)


def test_a_leaf_whose_line_cannot_be_found_falls_back_to_its_parent() -> None:
    """A citation must never be invented.

    A JSON leaf's path comes from the parsed structure, which carries no line
    information; the line is recovered by matching text. When that match fails
    the symbol still exists — it is a real key — but it cites the parent block
    rather than a line the parser guessed.
    """
    # `deep.a.b` is real, but the leaf `b` never appears on a line of its own.
    content = b'{\n  "deep": {"a": {"b": 1}}\n}\n'
    keys = _keys(content, "deep.json", "json")

    assert "deep.a.b" in keys
    start, end = keys["deep.a.b"]
    assert start <= 2 <= end


def _hashes(content: bytes, path: str, language: str) -> dict[str, str]:
    result = DocumentParser().parse(_request(content, path, language))
    return {
        symbol.qualified_name: symbol.content_hash
        for symbol in result.symbols
        if symbol.kind is SymbolKind.CONFIG_KEY
    }


def test_an_unchanged_nested_key_keeps_its_hash_when_a_sibling_changes() -> None:
    """The ADR-0025 regression: one edit reported eight keys as changed.

    A leaf whose own line cannot be located keeps its *parent's* range so the
    citation is never invented. Hashing the content of that range means the
    leaf hashes the whole parent block -- so any edit anywhere inside the block
    marks every such leaf modified. Changing one line of this project's
    `pyproject.toml` produced 8 CONFIG_VALUE_CHANGED findings, 7 of them false.

    The range is for *citation*. The hash must identify the leaf's own value.
    """
    before = (
        b'[project]\nversion = "0.1.0"\n\n'
        b'[project.scripts]\nrun = "app:main"\n'
    )
    after = (
        b'[project]\nversion = "9.9.9"\n\n'
        b'[project.scripts]\nrun = "app:main"\n'
    )

    old = _hashes(before, "pyproject.toml", "toml")
    new = _hashes(after, "pyproject.toml", "toml")

    assert old["project.version"] != new["project.version"], (
        "the key that actually changed must change"
    )
    # `project.scripts` is the case that breaks: it is a TOML table header,
    # `[project.scripts]`, which `_leaf_line`'s `key =` pattern cannot match,
    # so it falls back to the parent range and hashes the whole block.
    # `project.scripts.run` is deliberately NOT the assertion here -- `run`
    # resolves to its own line, so it was never affected and asserting on it
    # passes without testing anything.
    assert old["project.scripts"] == new["project.scripts"], (
        "an untouched nested key must not report as changed"
    )


def test_two_leaves_with_equal_values_under_one_parent_stay_distinct() -> None:
    """Hashing the value must not collapse two different keys into one.

    `a` and `b` hold the same value here. If the hash were the bare value they
    would share a content hash, and a rename or a move between them would be
    invisible to change detection -- trading one false-negative class for
    another.
    """
    content = b'{\n  "deep": {"a": 1, "b": 1}\n}\n'

    hashes = _hashes(content, "deep.json", "json")

    assert hashes["deep.a"] != hashes["deep.b"]
