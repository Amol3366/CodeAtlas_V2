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
