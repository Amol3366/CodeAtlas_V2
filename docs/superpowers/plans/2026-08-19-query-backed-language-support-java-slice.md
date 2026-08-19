# Query-Backed Language Support — Shared Engine and Java Slice

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared query-backed parser engine and the complete Java slice on it, ending at a hard checkpoint that proves or disproves whether `resolution.py` generalizes to a non-Python module system.

**Architecture:** One `TagsBackedParser` engine executes each grammar's shipped `tags.scm` plus an `imports.scm` authored here, and delegates the parts that need real logic to a thin per-language adapter implementing five methods. The engine stays a pure function of one `ParseRequest` — it never reads a second file — so imports are emitted as `SymbolReference`s carrying target hints and resolution happens later against the whole snapshot, exactly as `python_relations.py` and `tsjs_relations.py` already do.

**Tech Stack:** Python 3.12, `tree-sitter>=0.25,<0.27` (`Language`, `Parser`, `Query`, `QueryCursor`), `tree-sitter-java`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-query-backed-language-support-design.md`
**Decision record:** `docs/adr/0065-query-backed-language-support.md` (`accepted` 2026-08-19)

## Scope of this plan

This plan covers **the shared engine and Java only**, ending at Task 7.

Go, Rust, and Scala are approved in ADR-0065 but are **deliberately not planned here.** Task 7 verifies the spec's one unmeasured assumption — that `resolution.py` generalizes to a non-Python module system. The task shape for the other three languages depends on its answer, and writing them now would be planning on the assumption the checkpoint exists to test.

## Global Constraints

Copied verbatim from `AGENTS.md`, ADR-0065, and lessons this repository has already paid for.

- `AGENTS.md` is the release-blocking contract. `docs/plans/PLAN.md` is live status; **append** handoffs, never rewrite them.
- **Test-first.** No production code without a test observed failing first.
- **Mutation-check every fix.** A test that passes on its first run proves nothing until you have watched it fail. Revert a mutation **from a file copy, never `git checkout --`** — that has twice reverted the fix along with the mutation (ADR-0022, ADR-0042).
- **A parse is a pure function of the `ParseRequest`.** The engine must never read another file, resolve an import, or execute anything (`AGENTS.md` §4.4).
- **`domain/` imports nothing outward.** New code lives in `parsing/` and `extraction/` only, plus four suffix entries in `repositories/classification.py`.
- **ADR-0003: the corpus is never edited to move a number.** Adding coverage is legitimate; changing an expectation is not.
- **Declare version changes explicitly.** `PARSER_BUNDLE_VERSION` **1.4.0 → 1.5.0** is approved and lands in Task 8. `RESOLVER_VERSION` stays `1.4.0` unless Task 7 proves otherwise.
- `SCHEMA_VERSION` stays **14**. `contract_version` stays **1.1**. No migration.
- **`$?` after a pipe is the pipe's exit code, not the command's.** Capture into a variable or use `${PIPESTATUS[0]}`.
- **A gate script aborts at its first failing step**, so a red step one hides everything after it.
- Gates before any completion claim: `uv run pytest -q`, `ruff check src tests scripts apps`, `mypy --no-incremental src tests scripts apps`. Record exact commands and exit codes read from the process.

---

### Task 1: Dependencies and file classification

Four grammar packages and four suffixes. All four languages' dependencies land together so the lockfile churns once rather than four times.

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Modify: `src/codeatlas/repositories/classification.py:16-31` (`_LANGUAGE_BY_SUFFIX`)
- Test: `tests/unit/test_classification.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_LANGUAGE_BY_SUFFIX` maps `.java`→`"java"`, `.go`→`"go"`, `.rs`→`"rust"`, `.scala`→`"scala"`. Grammar modules `tree_sitter_java`, `tree_sitter_go`, `tree_sitter_rust`, `tree_sitter_scala` are importable.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_classification.py`:

```python
import pytest

from codeatlas.repositories.classification import detect_language


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/main/java/com/shop/OrderService.java", "java"),
        ("internal/orders/service.go", "go"),
        ("src/orders/service.rs", "rust"),
        ("src/main/scala/shop/OrderService.scala", "scala"),
    ],
)
def test_query_backed_languages_are_classified(path: str, expected: str) -> None:
    assert detect_language(path) == expected
```

If `detect_language` is not the public name in that module, read `classification.py` and use the function the existing tests in this file already call. Do not add a new entry point.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_classification.py -k query_backed -v`
Expected: FAIL — all four parametrizations return `None` or `"unknown"` rather than the language.

- [ ] **Step 3: Add the dependencies**

```bash
uv add "tree-sitter-java>=0.23,<0.24" "tree-sitter-go>=0.23,<0.24" \
       "tree-sitter-rust>=0.23,<0.25" "tree-sitter-scala>=0.23,<0.25"
```

If a floor does not resolve, run `uv add tree-sitter-java` unpinned first, read the resolved version, then pin to that minor with an exclusive upper bound matching the style of the three existing grammar pins in `pyproject.toml`. **Do not widen the `tree-sitter>=0.25,<0.27` pin.**

- [ ] **Step 4: Add the four suffixes**

In `src/codeatlas/repositories/classification.py`, extend `_LANGUAGE_BY_SUFFIX`:

```python
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".scala": "scala",
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_classification.py -v`
Expected: PASS, and every pre-existing test in the file still passes.

- [ ] **Step 6: Verify the grammars load**

Run:
```bash
uv run python -c "
import tree_sitter_java, tree_sitter_go, tree_sitter_rust, tree_sitter_scala
from tree_sitter import Language
for m in (tree_sitter_java, tree_sitter_go, tree_sitter_rust, tree_sitter_scala):
    Language(m.language())
print('all four grammars load')
"
```
Expected: `all four grammars load`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/codeatlas/repositories/classification.py tests/unit/test_classification.py
git commit -m "feat(classification): recognise Java, Go, Rust and Scala (ADR-0065)"
```

---

### Task 2: The language profile and adapter contracts

Pure declarations, no behaviour. Splitting this from the engine means a reviewer can reject the contract shape before any code depends on it.

**Files:**
- Create: `src/codeatlas/parsing/query_backed/__init__.py`
- Create: `src/codeatlas/parsing/query_backed/profile.py`
- Test: `tests/unit/test_query_backed_profile.py`

**Interfaces:**
- Consumes: `SymbolKind` from `codeatlas.contracts`; `Visibility`, `SymbolRecord` from `codeatlas.domain.symbols`; `SymbolReference` from `codeatlas.domain.relations`.
- Produces: `LanguageProfile` (frozen dataclass) and `LanguageAdapter` (Protocol), imported by Task 3's engine and Task 4's Java adapter.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_query_backed_profile.py`:

```python
import dataclasses

from codeatlas.contracts import SymbolKind
from codeatlas.parsing.query_backed.profile import LanguageProfile


def test_profile_is_frozen_and_carries_its_capture_map() -> None:
    profile = LanguageProfile(
        language="java",
        grammar=object(),
        tags_query=object(),
        imports_query=object(),
        kind_by_capture={"definition.class": SymbolKind.CLASS},
        scope_node_types=frozenset({"class_declaration"}),
    )
    assert profile.language == "java"
    assert profile.kind_by_capture["definition.class"] is SymbolKind.CLASS
    assert dataclasses.is_dataclass(profile)
    try:
        profile.language = "go"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("LanguageProfile must be frozen")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_query_backed_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codeatlas.parsing.query_backed'`.

- [ ] **Step 3: Write the contracts**

Create `src/codeatlas/parsing/query_backed/__init__.py` as an empty file.

Create `src/codeatlas/parsing/query_backed/profile.py`:

```python
"""Contracts for query-backed language support.

A profile is the data a language contributes; an adapter is the small amount of
behaviour a language needs that no query can express. The split is not
stylistic: measurement on 2026-08-19 showed Go's method receiver is a *field* of
the method node rather than a lexical ancestor, so a purely declarative design
produces a wrong qualified name rather than a missing one (ADR-0065).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from codeatlas.contracts import SymbolKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import Visibility


@dataclass(frozen=True)
class LanguageProfile:
    """Everything a language contributes as data rather than as behaviour."""

    language: str
    grammar: Any
    tags_query: Any
    imports_query: Any
    kind_by_capture: Mapping[str, SymbolKind]
    scope_node_types: frozenset[str]


class LanguageAdapter(Protocol):
    """The behaviour a language needs that no query can express."""

    profile: LanguageProfile

    def module_path(self, root: Any, source: bytes, relative_path: str) -> str:
        """The module or package this file declares, dotted."""

    def qualified_name(
        self, node: Any, name: str, scopes: Sequence[str], source: bytes
    ) -> str:
        """The symbol's fully qualified name within its module."""

    def owner_hint(self, node: Any, source: bytes) -> str | None:
        """The type owning this definition when it is not a lexical ancestor."""

    def imports(
        self, root: Any, source: bytes, file_id: str, module_symbol_id: str
    ) -> Iterable[SymbolReference]:
        """IMPORTS references this file declares. Never resolved here."""

    def visibility(self, node: Any, name: str, source: bytes) -> Visibility:
        """Whether the symbol is visible outside its module."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_query_backed_profile.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codeatlas/parsing/query_backed/ tests/unit/test_query_backed_profile.py
git commit -m "feat(parsing): language profile and adapter contracts (ADR-0065)"
```

---

### Task 3: The engine — definitions into SymbolRecords

The engine executes `tags.scm` and builds `SymbolRecord`s. Java is used as the vehicle because a query engine cannot be tested without a grammar, but nothing Java-specific belongs in this file.

**Files:**
- Create: `src/codeatlas/parsing/query_backed/engine.py`
- Test: `tests/unit/test_query_backed_engine.py`

**Interfaces:**
- Consumes: `LanguageProfile`, `LanguageAdapter` (Task 2); `ParseRequest`, `ParseResult`, `ParseDiagnostic`, `PARSER_BUNDLE_VERSION` from `codeatlas.parsing.registry`; `symbol_id`, `symbol_version_id` from `codeatlas.domain.ids`.
- Produces: `TagsBackedParser(adapter: LanguageAdapter)` with `name: str`, `version: str`, `supported_languages: frozenset[str]`, and `parse(request: ParseRequest) -> ParseResult`. Satisfies the existing `LanguageParser` protocol, so `ParserRegistry.register` accepts it unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_query_backed_engine.py`:

```python
from codeatlas.contracts import SymbolKind
from codeatlas.parsing.query_backed.languages.java import JavaAdapter
from codeatlas.parsing.query_backed.engine import TagsBackedParser
from codeatlas.parsing.registry import ParseRequest

SOURCE = b"""package com.shop.orders;

public interface Auditable {
    void audit(String reason);
}

public class OrderService implements Auditable {
    public void audit(String reason) {}
}
"""


def _request(content: bytes = SOURCE) -> ParseRequest:
    return ParseRequest(
        repository_id="repo_test",
        snapshot_id="snap_test",
        file_id="file_test",
        relative_path="src/main/java/com/shop/orders/OrderService.java",
        language="java",
        content=content,
    )


def test_definitions_become_symbols_with_kinds_and_lines() -> None:
    result = TagsBackedParser(JavaAdapter()).parse(_request())
    assert result.success
    by_name = {symbol.name: symbol for symbol in result.symbols}
    assert by_name["OrderService"].kind is SymbolKind.CLASS
    assert by_name["Auditable"].kind is SymbolKind.INTERFACE
    assert by_name["OrderService"].start_line == 7


def test_an_empty_file_yields_no_symbols_and_still_succeeds() -> None:
    result = TagsBackedParser(JavaAdapter()).parse(_request(b""))
    assert result.success
    assert result.symbols == ()


def test_an_oversized_file_is_refused_rather_than_parsed() -> None:
    from codeatlas.parsing.query_backed.engine import MAX_PARSE_BYTES

    result = TagsBackedParser(JavaAdapter()).parse(_request(b"a" * (MAX_PARSE_BYTES + 1)))
    assert not result.success
    assert [d.code for d in result.diagnostics] == ["PARSE_TOO_LARGE"]
```

The empty-file case matters for a reason worth knowing: an empty file has zero lines, so there is no line a module symbol could cite, and inventing line 1 fails snapshot validation. `python_parser.py` has the same guard and the same comment.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_query_backed_engine.py -v`
Expected: FAIL with `ModuleNotFoundError` for `codeatlas.parsing.query_backed.engine`.

- [ ] **Step 3: Write the engine**

Create `src/codeatlas/parsing/query_backed/engine.py`:

```python
"""A parser driven by Tree-sitter queries rather than hand-written traversal.

Each grammar ships a ``tags.scm`` declaring its definitions and references. That
is enough for a symbol inventory and is *not* enough for a relation graph: no
shipped ``tags.scm`` captures an import (measured across nine grammars,
2026-08-19), and resolution is built on the import graph. Imports therefore come
from a query authored in this repository and interpreted by the adapter.

A parse is a pure function of its request. Nothing here reads a second file,
resolves a name, or executes anything.
"""

from __future__ import annotations

import hashlib
from typing import Any

from tree_sitter import Parser as TreeSitterParser
from tree_sitter import QueryCursor

from codeatlas.domain.ids import symbol_id, symbol_version_id
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.query_backed.profile import LanguageAdapter
from codeatlas.parsing.registry import (
    PARSER_BUNDLE_VERSION,
    ParseDiagnostic,
    ParseRequest,
    ParseResult,
)

MAX_PARSE_BYTES = 2_000_000


class TagsBackedParser:
    """Extracts symbols and references using a language's query profile."""

    def __init__(self, adapter: LanguageAdapter) -> None:
        self._adapter = adapter
        self._profile = adapter.profile
        self.name = f"query-{self._profile.language}"
        self.version = PARSER_BUNDLE_VERSION
        self.supported_languages = frozenset({self._profile.language})
        self._parser = TreeSitterParser(self._profile.grammar)

    def parse(self, request: ParseRequest) -> ParseResult:
        if not request.content:
            return self._empty(success=True)
        if len(request.content) > MAX_PARSE_BYTES:
            return self._failed(
                ParseDiagnostic(
                    code="PARSE_TOO_LARGE",
                    message="the file is larger than the parser will accept",
                )
            )
        tree = self._parser.parse(request.content)
        module_path = self._adapter.module_path(
            tree.root_node, request.content, request.relative_path
        )
        symbols = self._definitions(tree.root_node, request, module_path)
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            symbols=tuple(symbols),
            diagnostics=(),
        )

    def _definitions(
        self, root: Any, request: ParseRequest, module_path: str
    ) -> list[SymbolRecord]:
        matches = QueryCursor(self._profile.tags_query).matches(root)
        records: list[SymbolRecord] = []
        for _pattern, captures in matches:
            kind = None
            definition_node = None
            for capture_name, nodes in captures.items():
                if capture_name in self._profile.kind_by_capture:
                    kind = self._profile.kind_by_capture[capture_name]
                    definition_node = nodes[0]
            name_nodes = captures.get("name") or ()
            if kind is None or definition_node is None or not name_nodes:
                continue
            name = self._text(name_nodes[0], request.content)
            # Ask the adapter for an owner first. Go's receiver is a *field* of
            # the method node, not an ancestor, so lexical scope is the wrong
            # answer there and this hook is the reason the design is not purely
            # declarative (ADR-0065).
            owner = self._adapter.owner_hint(definition_node, request.content)
            scopes = (
                [owner] if owner else self._scopes(definition_node, request.content)
            )
            qualified_name = self._adapter.qualified_name(
                definition_node, name, scopes, request.content
            )
            records.append(
                self._record(definition_node, request, kind, name, qualified_name, module_path)
            )
        return records

    def _scopes(self, node: Any, source: bytes) -> list[str]:
        """Enclosing scope names, outermost first.

        The adapter may ignore this entirely — Go's receiver is a field of the
        method node, not an ancestor, so lexical scope is the wrong answer there.
        """
        names: list[str] = []
        current = node.parent
        while current is not None:
            if current.type in self._profile.scope_node_types:
                named = current.child_by_field_name("name")
                if named is not None:
                    names.append(self._text(named, source))
            current = current.parent
        return list(reversed(names))

    def _record(
        self,
        node: Any,
        request: ParseRequest,
        kind: Any,
        name: str,
        qualified_name: str,
        module_path: str,
    ) -> SymbolRecord:
        definition_bytes = request.content[node.start_byte : node.end_byte]
        content_hash = hashlib.sha256(definition_bytes).hexdigest()
        logical_id = symbol_id(
            request.repository_id, request.relative_path, qualified_name, kind.value
        )
        return SymbolRecord(
            symbol_id=logical_id,
            symbol_version_id=symbol_version_id(
                logical_id, content_hash, PARSER_BUNDLE_VERSION
            ),
            file_id=request.file_id,
            kind=kind,
            name=name,
            qualified_name=qualified_name,
            module_path=module_path,
            signature=None,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            content_hash=content_hash,
            visibility=self._adapter.visibility(node, name, request.content),
        )

    @staticmethod
    def _text(node: Any, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", "replace")

    def _empty(self, *, success: bool) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=success,
            symbols=(),
            diagnostics=(),
        )

    def _failed(self, diagnostic: ParseDiagnostic) -> ParseResult:
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=False,
            symbols=(),
            diagnostics=(diagnostic,),
        )
```

If `QueryCursor.matches` returns a different shape in the pinned `tree-sitter` version, adapt the unpacking in `_definitions` — but keep using `matches`, **not** `captures`. `captures` returns a flat capture-name→nodes mapping with no association between a definition and its name, which is precisely the pairing this method needs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_query_backed_engine.py -v`
Expected: PASS — after Task 4 provides `JavaAdapter`. **This task's tests will not pass until Task 4 lands.** Implement Task 4 next, then return here and confirm before committing either.

- [ ] **Step 5: Commit**

```bash
git add src/codeatlas/parsing/query_backed/engine.py tests/unit/test_query_backed_engine.py
git commit -m "feat(parsing): query-backed parser engine (ADR-0065)"
```

---

### Task 4: The Java adapter and its import query

**Files:**
- Create: `src/codeatlas/parsing/query_backed/languages/__init__.py`
- Create: `src/codeatlas/parsing/query_backed/languages/java.py`
- Create: `src/codeatlas/parsing/query_backed/queries/java.imports.scm`
- Test: `tests/unit/test_java_adapter.py`

**Interfaces:**
- Consumes: `LanguageProfile`, `LanguageAdapter` (Task 2).
- Produces: `JavaAdapter()` satisfying `LanguageAdapter`, with `profile.language == "java"`. Used by Task 3's engine and Task 5's registration.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_java_adapter.py`:

```python
from tree_sitter import Parser as TreeSitterParser

from codeatlas.parsing.query_backed.languages.java import JavaAdapter

SOURCE = b"""package com.shop.orders;

import com.shop.payments.PaymentService;
import java.util.List;

public class OrderService {
    private int count;
    public void audit(String reason) {}
}
"""


def _root(source: bytes = SOURCE):
    adapter = JavaAdapter()
    return TreeSitterParser(adapter.profile.grammar).parse(source).root_node, adapter


def test_module_path_comes_from_the_package_declaration() -> None:
    root, adapter = _root()
    assert adapter.module_path(root, SOURCE, "src/main/java/com/shop/orders/X.java") == (
        "com.shop.orders"
    )


def test_module_path_falls_back_to_the_path_when_no_package_is_declared() -> None:
    source = b"public class Loose {}\n"
    root, adapter = _root(source)
    assert adapter.module_path(root, source, "src/Loose.java") == "src.Loose"


def test_a_method_is_qualified_by_its_enclosing_class() -> None:
    root, adapter = _root()
    assert adapter.qualified_name(root, "audit", ["OrderService"], SOURCE) == (
        "OrderService.audit"
    )


def test_imports_name_the_bound_symbol_not_the_package() -> None:
    root, adapter = _root()
    hints = {ref.target_hint for ref in adapter.imports(root, SOURCE, "file_x", "sym_mod")}
    assert "PaymentService" in hints
    assert "List" in hints
```

The last assertion is ADR-0039's rule applied to Java: `import x.Y` binds `Y`, so `IMPORTS` targets the bound symbol rather than the package.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_java_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError` for `codeatlas.parsing.query_backed.languages.java`.

- [ ] **Step 3: Write the import query**

Create `src/codeatlas/parsing/query_backed/queries/java.imports.scm`:

```scheme
; No shipped tags.scm captures an import (ADR-0065). This supplies the gap.
(import_declaration (scoped_identifier) @import.path) @import.statement
(import_declaration (identifier) @import.path) @import.statement
(package_declaration (scoped_identifier) @package.name)
(package_declaration (identifier) @package.name)
```

- [ ] **Step 4: Write the adapter**

Create `src/codeatlas/parsing/query_backed/languages/__init__.py` as an empty file.

Create `src/codeatlas/parsing/query_backed/languages/java.py`:

```python
"""Java adapter: the parts of Java that no query can express."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from typing import Any

import tree_sitter_java
from tree_sitter import Language, Query, QueryCursor

from codeatlas.contracts import RelationKind, SymbolKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import Visibility
from codeatlas.parsing.query_backed.profile import LanguageProfile
from codeatlas.parsing.query_backed.queries import load_query_source, load_tags_source

_KIND_BY_CAPTURE = {
    "definition.class": SymbolKind.CLASS,
    "definition.interface": SymbolKind.INTERFACE,
    "definition.method": SymbolKind.METHOD,
}

_SCOPE_NODE_TYPES = frozenset(
    {"class_declaration", "interface_declaration", "enum_declaration"}
)


class JavaAdapter:
    """Module paths, qualified names, imports, and visibility for Java."""

    def __init__(self) -> None:
        grammar = Language(tree_sitter_java.language())
        self.profile = LanguageProfile(
            language="java",
            grammar=grammar,
            tags_query=Query(grammar, load_tags_source("tree_sitter_java")),
            imports_query=Query(grammar, load_query_source("java.imports.scm")),
            kind_by_capture=_KIND_BY_CAPTURE,
            scope_node_types=_SCOPE_NODE_TYPES,
        )

    def module_path(self, root: Any, source: bytes, relative_path: str) -> str:
        for _pattern, captures in QueryCursor(self.profile.imports_query).matches(root):
            for node in captures.get("package.name", ()):
                return _text(node, source)
        # A file with no package declaration is in the default package. Falling
        # back to the path keeps module_path non-empty, which snapshot
        # validation requires, and keeps it stable across edits.
        path = PurePosixPath(relative_path)
        return ".".join([*path.parent.parts, path.stem])

    def qualified_name(
        self, node: Any, name: str, scopes: Sequence[str], source: bytes
    ) -> str:
        return ".".join([*scopes, name]) if scopes else name

    def owner_hint(self, node: Any, source: bytes) -> str | None:
        # Java owners are lexical ancestors, so scopes already carry them.
        return None

    def imports(
        self, root: Any, source: bytes, file_id: str, module_symbol_id: str
    ) -> Iterable[SymbolReference]:
        for _pattern, captures in QueryCursor(self.profile.imports_query).matches(root):
            statements = captures.get("import.statement", ())
            paths = captures.get("import.path", ())
            if not statements or not paths:
                continue
            statement, path = statements[0], paths[0]
            dotted = _text(path, source)
            # `import a.b.C` binds `C`, so IMPORTS targets the bound symbol
            # rather than the package (ADR-0039's rule, applied to Java).
            bound = dotted.rsplit(".", 1)[-1]
            yield SymbolReference(
                source_symbol_id=module_symbol_id,
                file_id=file_id,
                kind=RelationKind.IMPORTS,
                target_hint=bound,
                module_hint=dotted.rsplit(".", 1)[0] if "." in dotted else "",
                start_line=statement.start_point[0] + 1,
                end_line=statement.end_point[0] + 1,
            )

    def visibility(self, node: Any, name: str, source: bytes) -> Visibility:
        for child in node.children:
            if child.type == "modifiers" and b"public" in source[
                child.start_byte : child.end_byte
            ]:
                return "public"
        return "private"


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")
```

- [ ] **Step 5: Write the query loader**

Create `src/codeatlas/parsing/query_backed/queries/__init__.py`:

```python
"""Loads query sources: ours from this directory, tags.scm from the grammar."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

_HERE = Path(__file__).parent


def load_query_source(filename: str) -> str:
    """Read a query authored in this repository."""
    return (_HERE / filename).read_text(encoding="utf-8")


def load_tags_source(module_name: str) -> str:
    """Read the tags.scm a grammar package ships.

    Nine of eleven grammars ship one; a grammar that does not cannot use this
    engine, and saying so loudly beats returning an empty query that silently
    finds no symbols.
    """
    module = importlib.import_module(module_name)
    assert module.__file__ is not None
    for root, _dirs, files in os.walk(Path(module.__file__).parent):
        if "tags.scm" in files:
            return (Path(root) / "tags.scm").read_text(encoding="utf-8")
    raise FileNotFoundError(f"{module_name} ships no tags.scm")
```

- [ ] **Step 6: Run both test files to verify they pass**

Run: `uv run pytest tests/unit/test_java_adapter.py tests/unit/test_query_backed_engine.py -v`
Expected: PASS. Task 3's tests now have their adapter.

- [ ] **Step 7: Mutation-check the import rule**

Change `bound = dotted.rsplit(".", 1)[-1]` to `bound = dotted` in `java.py`.
Run: `uv run pytest tests/unit/test_java_adapter.py -k imports_name -v`
Expected: FAIL — the hint becomes `com.shop.payments.PaymentService` rather than `PaymentService`.
**Restore from a file copy, not `git checkout --`**, then re-run and confirm PASS.

- [ ] **Step 8: Commit**

```bash
git add src/codeatlas/parsing/query_backed/ tests/unit/test_java_adapter.py tests/unit/test_query_backed_engine.py
git commit -m "feat(parsing): Java adapter and import query (ADR-0065)"
```

---

### Task 5: Register Java, and emit its references

Wires the parser into the registry and adds `CALLS` and `IMPLEMENTS` from `tags.scm`, plus `IMPORTS` from Task 4.

**Files:**
- Create: `src/codeatlas/extraction/query_relations.py`
- Modify: `src/codeatlas/parsing/registry.py:113-124` (`default_registry`)
- Modify: `src/codeatlas/parsing/query_backed/engine.py` (populate `ParseResult.references`)
- Test: `tests/unit/test_query_relations.py`

**Interfaces:**
- Consumes: `JavaAdapter` (Task 4), `TagsBackedParser` (Task 3).
- Produces: `extract_query_references(root, source, request, adapter, symbols) -> tuple[SymbolReference, ...]`, called by `TagsBackedParser.parse`. `default_registry()` returns a registry whose `parser_for("java")` is not `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_query_relations.py`:

```python
from codeatlas.contracts import RelationKind
from codeatlas.parsing.query_backed.languages.java import JavaAdapter
from codeatlas.parsing.query_backed.engine import TagsBackedParser
from codeatlas.parsing.registry import ParseRequest, default_registry

SOURCE = b"""package com.shop.orders;

import com.shop.payments.PaymentService;

public class OrderService implements Auditable {
    private PaymentService payments;
    public void capture(String orderId) {
        payments.charge(orderId);
    }
}
"""


def _request() -> ParseRequest:
    return ParseRequest(
        repository_id="repo_test",
        snapshot_id="snap_test",
        file_id="file_test",
        relative_path="src/main/java/com/shop/orders/OrderService.java",
        language="java",
        content=SOURCE,
    )


def test_java_is_registered_in_the_default_registry() -> None:
    assert default_registry().parser_for("java") is not None


def test_imports_calls_and_implements_are_all_emitted() -> None:
    result = TagsBackedParser(JavaAdapter()).parse(_request())
    kinds = {(ref.kind, ref.target_hint) for ref in result.references}
    assert (RelationKind.IMPORTS, "PaymentService") in kinds
    assert (RelationKind.CALLS, "charge") in kinds
    assert (RelationKind.IMPLEMENTS, "Auditable") in kinds


def test_every_reference_cites_a_line_inside_the_file() -> None:
    result = TagsBackedParser(JavaAdapter()).parse(_request())
    line_count = SOURCE.count(b"\n") + 1
    assert result.references
    for ref in result.references:
        assert 1 <= ref.start_line <= ref.end_line <= line_count
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_query_relations.py -v`
Expected: FAIL — `parser_for("java")` returns `None`, and `result.references` is empty.

- [ ] **Step 3: Write the reference extractor**

Create `src/codeatlas/extraction/query_relations.py`:

```python
"""Turns query captures into SymbolReferences.

A reference is what the file *said*. Nothing is resolved here: resolution needs
the whole snapshot and happens later, which is what lets an unchanged file's
references be reused verbatim.
"""

from __future__ import annotations

from typing import Any

from tree_sitter import QueryCursor

from codeatlas.contracts import RelationKind
from codeatlas.domain.relations import SymbolReference
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.query_backed.profile import LanguageAdapter
from codeatlas.parsing.registry import ParseRequest

_KIND_BY_CAPTURE = {
    "reference.call": RelationKind.CALLS,
    "reference.implementation": RelationKind.IMPLEMENTS,
    "reference.class": RelationKind.REFERENCES,
    "reference.type": RelationKind.REFERENCES,
    "reference.interface": RelationKind.REFERENCES,
}


def extract_query_references(
    root: Any,
    source: bytes,
    request: ParseRequest,
    adapter: LanguageAdapter,
    symbols: tuple[SymbolRecord, ...],
) -> tuple[SymbolReference, ...]:
    """Every reference this file states, attributed to its enclosing symbol."""
    module_symbol_id = symbols[0].symbol_id if symbols else f"module_{request.file_id}"
    references = list(
        adapter.imports(root, source, request.file_id, module_symbol_id)
    )
    parts: dict[tuple[str, RelationKind, str, int], int] = {}
    for _pattern, captures in QueryCursor(adapter.profile.tags_query).matches(root):
        for capture_name, nodes in captures.items():
            kind = _KIND_BY_CAPTURE.get(capture_name)
            if kind is None:
                continue
            for node in nodes:
                hint = source[node.start_byte : node.end_byte].decode("utf-8", "replace")
                line = node.start_point[0] + 1
                owner = _enclosing_symbol_id(line, symbols, module_symbol_id)
                # `part` distinguishes two otherwise-identical references on
                # one line, as in `f(f(x))`. Both are real edges.
                key = (owner, kind, hint, line)
                part = parts.get(key, 0)
                parts[key] = part + 1
                references.append(
                    SymbolReference(
                        source_symbol_id=owner,
                        file_id=request.file_id,
                        kind=kind,
                        target_hint=hint,
                        module_hint="",
                        start_line=line,
                        end_line=node.end_point[0] + 1,
                        part=part,
                    )
                )
    return tuple(references)


def _enclosing_symbol_id(
    line: int, symbols: tuple[SymbolRecord, ...], fallback: str
) -> str:
    """The innermost symbol whose range covers this line."""
    best: SymbolRecord | None = None
    for symbol in symbols:
        if symbol.start_line <= line <= symbol.end_line:
            if best is None or symbol.start_line > best.start_line:
                best = symbol
    return best.symbol_id if best is not None else fallback
```

- [ ] **Step 4: Call it from the engine**

In `engine.py`, add the import and replace the `return ParseResult(...)` in `parse` so references are populated:

```python
from codeatlas.extraction.query_relations import extract_query_references
```

```python
        symbols = tuple(self._definitions(tree.root_node, request, module_path))
        references = extract_query_references(
            tree.root_node, request.content, request, self._adapter, symbols
        )
        return ParseResult(
            parser_name=self.name,
            parser_version=self.version,
            success=True,
            symbols=symbols,
            diagnostics=(),
            references=references,
        )
```

- [ ] **Step 5: Register the parser**

In `src/codeatlas/parsing/registry.py`, inside `default_registry`:

```python
    from codeatlas.parsing.query_backed.engine import TagsBackedParser
    from codeatlas.parsing.query_backed.languages.java import JavaAdapter
```

```python
    registry.register(TagsBackedParser(JavaAdapter()))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_query_relations.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole unit suite for regressions**

Run: `uv run pytest tests/unit -q`
Expected: PASS. `ParserRegistry.register` raises on a duplicate language, so a collision with an existing parser surfaces here rather than silently depending on import order.

- [ ] **Step 8: Commit**

```bash
git add src/codeatlas/extraction/query_relations.py src/codeatlas/parsing/ tests/unit/test_query_relations.py
git commit -m "feat(extraction): Java references and registry wiring (ADR-0065)"
```

---

### Task 6: A Java fixture repository

The fixture the checkpoint measures against. It declares expected symbols and relations, per `AGENTS.md` §19.2.

**Files:**
- Create: `tests/evaluation/cases/fixtures/java_app/src/main/java/com/shop/orders/OrderService.java`
- Create: `tests/evaluation/cases/fixtures/java_app/src/main/java/com/shop/payments/PaymentService.java`
- Modify: `tests/evaluation/cases/dataset.json`
- Modify: `tests/evaluation/test_dataset.py:24`
- Modify: the `SUPPORTED_FIXTURES` constant read by `tests/evaluation/test_engine_adapter.py:94`
- Test: `tests/integration/test_java_indexing.py`

**Interfaces:**
- Consumes: the registered Java parser (Task 5).
- Produces: fixture id `java_app` with two files in one snapshot, usable by Task 7.

- [ ] **Step 1: Write the fixture source**

`OrderService.java`:

```java
package com.shop.orders;

import com.shop.payments.PaymentService;

public class OrderService {
    private final PaymentService payments;

    public OrderService(PaymentService payments) {
        this.payments = payments;
    }

    public void capture(String orderId) {
        payments.charge(orderId);
    }
}
```

`PaymentService.java`:

```java
package com.shop.payments;

public class PaymentService {
    public void charge(String orderId) {
    }
}
```

The cross-package import is the whole point: `OrderService` must reach `PaymentService.charge` through a package that maps to a directory. That is the exact shape Task 7 tests.

- [ ] **Step 2: Declare the fixture**

In `tests/evaluation/cases/dataset.json`, add to `fixtures`, matching the existing entries' shape:

```json
{
  "id": "java_app",
  "root": "java_app",
  "kind": "java",
  "snapshots": [
    {
      "id": "java-v1",
      "members": [
        "src/main/java/com/shop/orders/OrderService.java",
        "src/main/java/com/shop/payments/PaymentService.java"
      ]
    }
  ]
}
```

- [ ] **Step 3: Update the two guards, deliberately**

In `tests/evaluation/test_dataset.py`, change `assert len(dataset.fixtures) == 7` to `== 8`.

Add `"java_app"` to `SUPPORTED_FIXTURES` (imported by `tests/evaluation/test_engine_adapter.py`; find its definition with `grep -rn "SUPPORTED_FIXTURES" src tests`).

**Both edits are required and neither is incidental.** `test_engine_adapter.py:94` asserts every corpus fixture except `malicious_unsupported` is in `SUPPORTED_FIXTURES` — ADR-0017's lesson wired into a test, so a fixture silently gated out of measurement fails the suite.

- [ ] **Step 4: Write the integration test**

Create `tests/integration/test_java_indexing.py`:

```python
from codeatlas.contracts import SymbolKind


def test_a_java_repository_indexes_into_symbols(index_fixture_repository) -> None:
    """Follow the pattern of the existing integration tests in this directory.

    Read tests/integration/test_incremental_indexing.py first and use whatever
    fixture or helper it uses to register and index a repository; do not invent
    a new harness.
    """
    snapshot = index_fixture_repository("java_app")
    names = {symbol.qualified_name for symbol in snapshot.symbols}
    assert "OrderService" in names
    assert "OrderService.capture" in names
    assert "PaymentService.charge" in names
    kinds = {s.qualified_name: s.kind for s in snapshot.symbols}
    assert kinds["OrderService"] is SymbolKind.CLASS
```

- [ ] **Step 5: Run it**

Run: `uv run pytest tests/integration/test_java_indexing.py tests/evaluation/test_dataset.py -v`
Expected: PASS. If the helper name differs, fix the test to match the existing harness rather than adding one.

- [ ] **Step 6: Extend the hostile-input coverage to the new extensions**

Spec §11. A new extension that path-safety never exercises is an untested
attack surface, and the existing suites are parameterised by extension.

Add a `.java` file to the `malicious_unsupported` fixture whose *path* is
hostile, mirroring whatever shapes that fixture already uses — read it first
with `ls tests/evaluation/cases/fixtures/malicious_unsupported`. Then add a
malformed-source test:

```python
def test_malformed_java_is_reported_not_raised() -> None:
    """Tree-sitter is error-tolerant; the parser must not be."""
    from codeatlas.parsing.query_backed.languages.java import JavaAdapter
    from codeatlas.parsing.query_backed.engine import TagsBackedParser
    from codeatlas.parsing.registry import ParseRequest

    broken = b"package com.shop; public class { { { void ((("
    result = TagsBackedParser(JavaAdapter()).parse(
        ParseRequest(
            repository_id="repo_test",
            snapshot_id="snap_test",
            file_id="file_test",
            relative_path="src/Broken.java",
            language="java",
            content=broken,
        )
    )
    # Whatever it yields, it must not raise and must not invent a symbol
    # whose range falls outside the file.
    line_count = broken.count(b"
") + 1
    for symbol in result.symbols:
        assert 1 <= symbol.start_line <= symbol.end_line <= line_count
```

Run: `uv run pytest tests/unit/test_query_backed_engine.py -k malformed -v` and
`uv run pytest tests/security -q`
Expected: both PASS. Repository fixtures are untrusted data and are never
imported, built, or executed.

- [ ] **Step 7: Commit**

```bash
git add tests/evaluation/cases/fixtures tests/evaluation/cases/dataset.json tests/evaluation/test_dataset.py tests/integration/test_java_indexing.py tests/unit/test_query_backed_engine.py
git commit -m "test(java): java_app fixture, indexing and hostile-input coverage (ADR-0065)"
```

---

### Task 7: ⛔ CHECKPOINT — does `resolution.py` generalize?

**This is the task the plan exists to reach.** ADR-0065 records one load-bearing assumption that was read from the code rather than measured: that `resolution.py` resolves Java's `com.shop.orders` ↔ `com/shop/orders/` through the `module_suffix_to_file` index ADR-0064 built, with no per-language rules.

**Stop at the end of this task and report to the user before starting Go, Rust, or Scala.**

**Files:**
- Test: `tests/integration/test_java_resolution.py`
- Modify (only if the assumption fails): `src/codeatlas/extraction/resolution.py`

**Interfaces:**
- Consumes: the `java_app` fixture (Task 6).
- Produces: a measured answer, and either an unchanged `RESOLVER_VERSION` or a recorded reason to bump it.

- [ ] **Step 1: Write the test that asks the question**

Create `tests/integration/test_java_resolution.py`:

```python
def test_a_java_import_resolves_across_packages(index_fixture_repository) -> None:
    """The assumption ADR-0065 could not verify without building this.

    `import com.shop.payments.PaymentService` must bind to the PaymentService
    symbol defined in another directory. If this fails, the resolver does not
    generalize and ADR-0065's cost estimate is wrong.
    """
    snapshot = index_fixture_repository("java_app")
    imports = [r for r in snapshot.relations if r.kind.value == "IMPORTS"]
    assert imports, "no IMPORTS relations were stored at all"
    resolved = [r for r in imports if r.resolution == "resolved"]
    assert resolved, f"no Java import resolved; states={[r.resolution for r in imports]}"


def test_a_java_call_resolves_to_the_imported_class_method(
    index_fixture_repository,
) -> None:
    snapshot = index_fixture_repository("java_app")
    calls = [
        r
        for r in snapshot.relations
        if r.kind.value == "CALLS" and r.target_hint == "charge"
    ]
    assert calls, "the call to charge was not recorded"
    assert any(r.resolution == "resolved" for r in calls), (
        f"charge never resolved; states={[r.resolution for r in calls]}"
    )
```

Match the attribute names to whatever the existing integration tests use for relations and resolution state; read `tests/integration/test_snapshot_isolation.py` first.

Add a third test, because spec §6 declares a derivation ladder that nothing else
in this plan pins:

```python
def test_a_resolved_java_edge_carries_a_defensible_derivation(
    index_fixture_repository,
) -> None:
    """Spec section 6: a resolved query-backed edge is static_resolved, and an
    unresolved one is never promoted. Query captures carry no receiver context,
    so this is the ceiling rather than parity with Python."""
    snapshot = index_fixture_repository("java_app")
    resolved = [r for r in snapshot.relations if r.resolution == "resolved"]
    assert resolved
    for relation in resolved:
        assert relation.derivation.value in {"static_resolved", "deterministic"}
    for relation in snapshot.relations:
        if relation.resolution != "resolved":
            assert relation.derivation.value != "deterministic"
```

- [ ] **Step 2: Run it and record the real answer**

Run: `uv run pytest tests/integration/test_java_resolution.py -v`

**Record the actual output, whichever way it goes.** Both outcomes are results:
- **PASS** — the assumption holds. `RESOLVER_VERSION` stays `1.4.0`, and ADR-0065's estimate for Go, Rust, and Scala stands.
- **FAIL** — the assumption is wrong, which is exactly what this checkpoint is for. Do **not** patch around it silently.

- [ ] **Step 3: If it failed, diagnose before changing anything**

Print what the resolver actually saw:

```bash
uv run python -c "
from codeatlas.extraction.resolution import RESOLVER_VERSION
print('resolver', RESOLVER_VERSION)
"
```

Then read `_Index.module_suffix_to_file` in `src/codeatlas/extraction/resolution.py` and determine whether Java's dotted package fails to match a slash-separated directory path. **Write down the mechanism before writing a fix** — three consecutive records in this repository (ADR-0060 to ADR-0062) attributed a cost to the wrong stage by reasoning instead of measuring.

- [ ] **Step 4: If it failed, stop and report**

A resolver change is a `RESOLVER_VERSION` bump, which makes every snapshot stale a second time, and ADR-0065 explicitly scoped that as conditional. **Report the diagnosis to the user and get a decision before implementing.** Do not proceed to Go, Rust, or Scala.

- [ ] **Step 5: If it passed, commit and report**

```bash
git add tests/integration/test_java_resolution.py
git commit -m "test(java): resolution generalizes across packages (ADR-0065 checkpoint)"
```

Report to the user: the checkpoint passed, `RESOLVER_VERSION` is unchanged, and the remaining three languages can be planned.

---

### Task 8: Version bump, gates, and documentation

Only after Task 7 passes. This makes the work real for existing users, so it is deliberately last.

**Files:**
- Modify: `src/codeatlas/parsing/registry.py:37` (`PARSER_BUNDLE_VERSION`)
- Modify: `documentation/architecture.md` (stack table and folder structure)
- Modify: `README.md` (status row and Known Limits — Java moves from approved to shipped; Go, Rust, Scala stay approved-not-built)
- Modify: `docs/plans/PLAN.md` (append a handoff), `documentation/memory.md`

- [ ] **Step 1: Bump the parser bundle version**

In `src/codeatlas/parsing/registry.py`, following the comment style of the existing entries:

```python
# 1.5.0 (ADR-0065): a query-backed parser emits Java symbols and references, so
# every symbol version derived by the 1.4.0 bundle is stale.
PARSER_BUNDLE_VERSION: str = "1.5.0"
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. Record the count. Snapshot-identity tests that pin the bundle version will need updating — that is the bump working as designed, not a regression.

- [ ] **Step 3: Run lint and types**

Run: `ruff check src tests scripts apps`
Run: `mypy --no-incremental src tests scripts apps`
Expected: both clean. Read exit codes from the process, not from piped output.

- [ ] **Step 4: Regenerate the baselines**

Run: `uv run python scripts/run_evaluation.py validate`
Then regenerate `baseline-phase-0`, `-3`, and `-4` using the commands in `scripts/check_phase4.ps1`. **`baseline-phase-1` and `-2` stay frozen as history — do not regenerate them.**

Metrics will move because the corpus grew. **A drop is a wider measurement, not automatically a regression** (ADR-0065). Record before-and-after values in the handoff; do not trim the corpus to protect a number.

- [ ] **Step 5: Run the phase gate**

Run: `powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1 -SkipSync`
Expected: exit 0. A gate aborts at its first failing step, so if an early stage fails, nothing after it ran.

- [ ] **Step 6: Update the documentation**

- `documentation/architecture.md`: add the four grammar dependencies to the backend stack table and `query_backed/` to the folder structure.
- `README.md`: Java moves from "approved but not built" to supported; **Go, Rust, and Scala stay approved-not-built** until their slices land.
- `docs/plans/PLAN.md`: append a handoff with the commands, exit codes, baseline movements, and the Task 7 result.
- `documentation/memory.md`: record what the checkpoint found.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(parsing): ship Java support, PARSER_BUNDLE_VERSION 1.4.0 -> 1.5.0 (ADR-0065)"
```

---

## After this plan

Go, Rust, and Scala each follow Tasks 4–7 with their own adapter, import query, fixture, and resolution check. Their plan is written **after** Task 7 reports, because its findings determine whether each language needs only an adapter or resolver work as well.

The measured expectation from ADR-0065 is roughly 1.5–2 days per language. Task 7 is what turns that from an estimate into a number.
