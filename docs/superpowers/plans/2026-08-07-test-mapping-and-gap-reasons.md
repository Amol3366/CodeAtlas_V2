# Fixture/Helper Test Mapping and Gap Reasons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect Python tests that reach a symbol through a pytest fixture or a test helper, record them as `TESTS` edges at `low_confidence_heuristic`, and give every remaining test gap a structured, evidence-backed reason.

**Architecture:** Follows the existing parse → reference → resolve pipeline. The parser learns to classify `@pytest.fixture` functions as `SymbolKind.FIXTURE` (a kind declared since Phase 0 and never emitted). Reference extraction emits a new intermediate `CONSUMES_FIXTURE` reference per injected test parameter. Two new derivation passes in `resolution.py` join those into weak `TESTS` edges. `impact.py` then reports both the weak edges and, separately, the reason each gap remains a gap.

**Tech Stack:** Python 3.12, `ast` (stdlib), Pydantic 2, pytest, SQLite. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-07-test-mapping-and-gap-reasons-design.md`

## Global Constraints

- `contract_version` stays `"1.1"`. Every contract change in this plan is additive.
- `SCHEMA_VERSION` stays `14`. **No migration is written.**
- Python is pinned `>=3.12,<3.13`. Do not add a dependency (`documentation/rules.md`, "Libraries").
- Type hints throughout. MyPy must pass. No `Any` where a type is knowable.
- A weak edge never overwrites, upgrades, or replaces a `high_confidence_heuristic` `TESTS` edge.
- A weak edge never removes a symbol from `test_gaps`.
- Never claim a symbol is tested or untested. Output describes the relation graph only.
- Do not edit `docs/evaluation/baseline-phase-4.*` or any Phase 4 gate artifact.
- Integration tests use real SQLite, real parsers, real application services. Mock external boundaries only.
- Comments explain *why*, not *what* (`documentation/rules.md`, "Code Style").
- Run the quality gate with `uv run` and record actual commands, exit codes, and output.

---

### Task 1: Classify `conftest.py` as test code

`conftest.py` at a repository root or beside a package is currently `SOURCE_CODE`, because `_is_test_path` only matches test directories and `test_*` / `*_test` / `*.spec` / `*.test` stems. Fixtures living there would be invisible to every later task, since `_derive_test_edges` gates on `FileClassification.TEST_CODE`.

**Files:**
- Modify: `src/codeatlas/repositories/classification.py:150-158`
- Test: `tests/unit/test_classification.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_is_test_path(stem: str, directories: tuple[str, ...]) -> bool` now returns `True` for `stem == "conftest"`. Later tasks rely on `conftest.py` carrying `FileClassification.TEST_CODE`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_classification.py`. Match the file's existing import style and its helper for invoking classification — read the top of the file first and follow it rather than inventing a new call shape.

```python
def test_a_root_conftest_is_test_code() -> None:
    classification, _ = classify_file("conftest.py")
    assert classification is FileClassification.TEST_CODE


def test_a_package_conftest_is_test_code() -> None:
    classification, _ = classify_file("src/orders/conftest.py")
    assert classification is FileClassification.TEST_CODE


def test_a_module_merely_starting_with_conftest_is_not_test_code() -> None:
    # Exact stem only. `conftest_helpers.py` is ordinary source.
    classification, _ = classify_file("src/orders/conftest_helpers.py")
    assert classification is FileClassification.SOURCE_CODE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_classification.py -k conftest -v`
Expected: the first two FAIL asserting `SOURCE_CODE is TEST_CODE`; the third passes already.

- [ ] **Step 3: Implement**

In `src/codeatlas/repositories/classification.py`, extend `_is_test_path`:

```python
def _is_test_path(stem: str, directories: tuple[str, ...]) -> bool:
    if any(directory in _TEST_DIRECTORIES for directory in directories):
        return True
    # `conftest.py` is pytest's fixture file and is frequently placed at a
    # repository root or beside a package, where no other rule here matches it.
    # Fixtures defined in one are invisible to test-edge derivation unless the
    # file is classified as test code.
    if stem == "conftest":
        return True
    return (
        stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith(".spec")
        or stem.endswith(".test")
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_classification.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Check nothing else classified differently**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: PASS. This change reclassifies real files, so a failure here is signal, not noise — if a test breaks, read it before changing it.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/repositories/classification.py tests/unit/test_classification.py
git commit -m "feat: classify conftest.py as test code"
```

---

### Task 2: Emit `SymbolKind.FIXTURE`

`SymbolKind.FIXTURE` is declared at `src/codeatlas/contracts.py:133` and reserved by `_UNTESTABLE_KINDS` (`src/codeatlas/analysis/impact.py:46`) and `src/codeatlas/analysis/findings.py:63`. Nothing has ever produced it.

**Files:**
- Modify: `src/codeatlas/parsing/python_parser.py:331-338` (`_function_kind`) and its call site in `_collect`
- Test: `tests/unit/test_python_parser.py`

**Interfaces:**
- Consumes: Task 1's `TEST_CODE` classification for `conftest.py`.
- Produces: `_function_kind(name: str, *, inside_class: bool, is_test_file: bool, decorators: list[ast.expr]) -> SymbolKind`. Module-level functions decorated with `pytest.fixture` or `fixture` now carry `SymbolKind.FIXTURE`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_python_parser.py`, following the file's existing parse-helper convention.

```python
def test_a_bare_pytest_fixture_is_a_fixture_symbol() -> None:
    result = parse_python("import pytest\n\n@pytest.fixture\ndef store():\n    return 1\n", path="conftest.py")
    assert kind_of(result, "store") is SymbolKind.FIXTURE


def test_a_called_pytest_fixture_is_a_fixture_symbol() -> None:
    source = 'import pytest\n\n@pytest.fixture(scope="session")\ndef store():\n    return 1\n'
    result = parse_python(source, path="conftest.py")
    assert kind_of(result, "store") is SymbolKind.FIXTURE


def test_a_bare_imported_fixture_name_is_a_fixture_symbol() -> None:
    source = "from pytest import fixture\n\n@fixture\ndef store():\n    return 1\n"
    result = parse_python(source, path="conftest.py")
    assert kind_of(result, "store") is SymbolKind.FIXTURE


def test_a_decorated_test_function_stays_a_test() -> None:
    # pytest collects this as a test. The TEST branch must win.
    source = "import pytest\n\n@pytest.fixture\ndef test_store():\n    return 1\n"
    result = parse_python(source, path="test_orders.py")
    assert kind_of(result, "test_store") is SymbolKind.TEST


def test_an_undecorated_function_in_a_test_file_is_a_function() -> None:
    result = parse_python("def build_store():\n    return 1\n", path="conftest.py")
    assert kind_of(result, "build_store") is SymbolKind.FUNCTION


def test_a_string_naming_pytest_fixture_classifies_nothing() -> None:
    # Matching reads the AST decorator name, never source text.
    source = 'def store():\n    """Use pytest.fixture for this."""\n    return 1\n'
    result = parse_python(source, path="conftest.py")
    assert kind_of(result, "store") is SymbolKind.FUNCTION


def test_an_unrelated_decorator_does_not_make_a_fixture() -> None:
    source = "import functools\n\n@functools.cache\ndef store():\n    return 1\n"
    result = parse_python(source, path="conftest.py")
    assert kind_of(result, "store") is SymbolKind.FUNCTION
```

If `parse_python` / `kind_of` helpers do not exist in that file under those names, use whatever the file already uses and keep the assertions identical.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_python_parser.py -k fixture -v`
Expected: the four FIXTURE-expecting tests FAIL with `SymbolKind.FUNCTION is not SymbolKind.FIXTURE`. The `test_store`, undecorated, string, and unrelated-decorator tests pass already — that is expected and correct; they are regression guards.

- [ ] **Step 3: Implement**

In `src/codeatlas/parsing/python_parser.py`, add the decorator matcher above `_function_kind`:

```python
# pytest's fixture decorator, as written at a definition site. Both the bare
# form (`@pytest.fixture`) and the called form (`@pytest.fixture(scope="session")`)
# appear, and either may be imported directly as `fixture`.
_FIXTURE_DECORATORS: Final[frozenset[str]] = frozenset(
    {"pytest.fixture", "fixture"}
)


def _decorator_name(node: ast.expr) -> str:
    """The dotted name a decorator expression names, or "" if it names none.

    The name is read from the AST, never from source text: a comment or a
    docstring mentioning `pytest.fixture` must not classify anything.
    """
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _decorator_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_fixture(decorators: list[ast.expr]) -> bool:
    return any(
        _decorator_name(decorator) in _FIXTURE_DECORATORS
        for decorator in decorators
    )
```

Then extend `_function_kind`:

```python
def _function_kind(
    name: str,
    *,
    inside_class: bool,
    is_test_file: bool,
    decorators: list[ast.expr],
) -> SymbolKind:
    if inside_class:
        return SymbolKind.CONSTRUCTOR if name == "__init__" else SymbolKind.METHOD
    # The TEST branch stays first: a `test_*` function carrying a fixture
    # decorator is still what pytest collects and runs as a test.
    if is_test_file and name.startswith("test_"):
        return SymbolKind.TEST
    if is_test_file and _is_fixture(decorators):
        return SymbolKind.FIXTURE
    return SymbolKind.FUNCTION
```

Update the call site inside `_collect` to pass `decorators=node.decorator_list`. Add `Final` to the module's `typing` import if it is not already there.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_python_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Run the broader suite**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: PASS. Fixtures now leave `SymbolKind.FUNCTION`, so any test asserting a fixture is a function is now asserting the old behavior — read it and update the expectation deliberately.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/parsing/python_parser.py tests/unit/test_python_parser.py
git commit -m "feat: classify pytest fixtures as SymbolKind.FIXTURE"
```

---

### Task 3: Emit `CONSUMES_FIXTURE` references

`extract_python_references` currently receives only `symbol_ids` (qualified name → id), so it cannot tell a `TEST` function from any other. This task threads kinds through and emits one reference per injected parameter.

**Files:**
- Modify: `src/codeatlas/contracts.py:141-158` (`RelationKind`)
- Modify: `src/codeatlas/extraction/python_relations.py:143-168` and `_walk_body`
- Modify: `src/codeatlas/parsing/python_parser.py:161-168` (call site)
- Modify: `src/codeatlas/extraction/resolution.py:59` (`RESOLVER_VERSION`)
- Test: `tests/unit/test_python_relations.py`

**Interfaces:**
- Consumes: Task 2's `SymbolKind.FIXTURE` and the existing `SymbolKind.TEST`.
- Produces: `RelationKind.CONSUMES_FIXTURE`. `extract_python_references(*, module, module_path, file_id, symbol_ids, symbol_kinds)` where `symbol_kinds: Mapping[str, SymbolKind]`. Emitted references carry `kind=CONSUMES_FIXTURE`, `target_hint=<parameter name>`, `module_hint=""`. `RESOLVER_VERSION == "1.2.0"`.

- [ ] **Step 1: Add the enum member**

In `src/codeatlas/contracts.py`, add to `RelationKind` after `TESTS`:

```python
    CONSUMES_FIXTURE = "CONSUMES_FIXTURE"
```

Additive — `contract_version` stays `"1.1"`.

- [ ] **Step 2: Write the failing tests**

Add to `tests/unit/test_python_relations.py`, following its existing extraction-helper convention.

```python
def test_a_test_parameter_becomes_a_fixture_reference() -> None:
    source = "def test_orders(store):\n    assert store\n"
    refs = fixture_references(source, path="test_orders.py")
    assert [(ref.target_hint, ref.module_hint) for ref in refs] == [("store", "")]


def test_each_parameter_becomes_its_own_reference() -> None:
    source = "def test_orders(store, clock):\n    assert store and clock\n"
    refs = fixture_references(source, path="test_orders.py")
    assert [ref.target_hint for ref in refs] == ["store", "clock"]


def test_parameters_on_one_line_get_distinct_parts() -> None:
    # `part` is what keeps two references on the same line apart.
    source = "def test_orders(store, clock):\n    assert store and clock\n"
    refs = fixture_references(source, path="test_orders.py")
    assert len({ref.part for ref in refs}) == 2


def test_a_defaulted_parameter_is_not_injected() -> None:
    # pytest does not inject a parameter that already has a value.
    source = "def test_orders(store, limit=5):\n    assert store and limit\n"
    refs = fixture_references(source, path="test_orders.py")
    assert [ref.target_hint for ref in refs] == ["store"]


def test_varargs_and_kwargs_are_not_injected() -> None:
    source = "def test_orders(store, *args, **kwargs):\n    assert store\n"
    refs = fixture_references(source, path="test_orders.py")
    assert [ref.target_hint for ref in refs] == ["store"]


def test_self_and_cls_are_not_injected() -> None:
    source = (
        "class TestOrders:\n"
        "    def test_orders(self, store):\n"
        "        assert store\n"
    )
    refs = fixture_references(source, path="test_orders.py")
    assert "self" not in [ref.target_hint for ref in refs]


def test_a_non_test_function_emits_no_fixture_reference() -> None:
    source = "def build_orders(store):\n    return store\n"
    refs = fixture_references(source, path="test_orders.py")
    assert refs == []
```

Write `fixture_references` as a local helper in the test module: parse the source, call the parser, and return every reference whose `kind is RelationKind.CONSUMES_FIXTURE`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_python_relations.py -k fixture -v`
Expected: FAIL — no `CONSUMES_FIXTURE` reference is produced, so the lists are empty.

- [ ] **Step 4: Thread symbol kinds through**

In `src/codeatlas/parsing/python_parser.py`, extend the call at line 161:

```python
        extraction = extract_python_references(
            module=module,
            module_path=module_path,
            file_id=request.file_id,
            symbol_ids={
                symbol.qualified_name: symbol.symbol_id for symbol in symbols
            },
            symbol_kinds={
                symbol.qualified_name: symbol.kind for symbol in symbols
            },
        )
```

In `src/codeatlas/extraction/python_relations.py`, add `symbol_kinds: Mapping[str, SymbolKind]` to the `extract_python_references` signature and to the `_Collector` dataclass, then pass it into the collector construction. Import `SymbolKind` from `codeatlas.contracts`.

- [ ] **Step 5: Emit the references**

Add to `_Collector`:

```python
    def add_fixture_parameters(
        self, *, source: str, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Record one reference per parameter pytest would inject into a test.

        Only a TEST symbol is considered. A fixture consumed by another fixture
        is a real pytest behavior, but chaining it would let one weak link
        stand on another, and the resulting edge would be too far from the
        evidence to be worth reporting.
        """
        if self.symbol_kinds.get(source) is not SymbolKind.TEST:
            return
        arguments = node.args
        # A defaulted parameter already has a value, so pytest does not inject
        # it. Defaults bind to the tail of `args`, hence the slice.
        defaulted = len(arguments.defaults)
        positional = arguments.posonlyargs + arguments.args
        injected = positional[: len(positional) - defaulted] if defaulted else positional
        for argument in injected:
            if argument.arg in {"self", "cls"}:
                continue
            self.add(
                source=source,
                kind=RelationKind.CONSUMES_FIXTURE,
                target_hint=argument.arg,
                module_hint="",
                start_line=node.lineno,
                end_line=node.lineno,
            )
```

`*args` and `**kwargs` are excluded by construction — neither `vararg` nor `kwarg` appears in `posonlyargs` or `args`. Keyword-only arguments are also excluded: pytest does not inject them.

In `_walk_body`, where a `FunctionDef` / `AsyncFunctionDef` is visited and its qualified name is already computed, call `collector.add_fixture_parameters(source=<qualified name>, node=node)`. Read the surrounding code and use the same variable the existing `collector.add(...)` calls use for `source`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_python_relations.py -v`
Expected: PASS.

- [ ] **Step 7: Bump `RESOLVER_VERSION`**

Stored relation output now differs, so derived rows from an earlier snapshot must not be reused. In `src/codeatlas/extraction/resolution.py:59`:

```python
RESOLVER_VERSION: str = "1.2.0"
```

- [ ] **Step 8: Run the broader suite**

Run: `uv run pytest tests/unit tests/integration tests/contract -q`
Expected: PASS. A contract test asserting the exact `RelationKind` member set will fail — update it to include `CONSUMES_FIXTURE` and confirm `contract_version` is still `"1.1"`.

- [ ] **Step 9: Commit**

```bash
git add src/codeatlas/contracts.py src/codeatlas/extraction/python_relations.py src/codeatlas/parsing/python_parser.py src/codeatlas/extraction/resolution.py tests/
git commit -m "feat: emit CONSUMES_FIXTURE references for injected test parameters"
```

---

### Task 4: Fixture-mediated `TESTS` derivation

**Files:**
- Modify: `src/codeatlas/extraction/resolution.py` (new `_derive_fixture_test_edges`, called from `resolve` after line 172)
- Test: `tests/unit/test_resolution.py`

**Interfaces:**
- Consumes: Task 3's `CONSUMES_FIXTURE` references; Task 2's `SymbolKind.FIXTURE`.
- Produces: `_derive_fixture_test_edges(relations: Sequence[RelationRecord], index: _Index) -> list[RelationRecord]`, emitting `RelationKind.TESTS` at `Derivation.LOW_CONFIDENCE_HEURISTIC`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_resolution.py`, using the file's existing resolver-invocation helper.

```python
def test_a_fixture_mediated_test_produces_a_weak_edge() -> None:
    # conftest.py builds the object; the test never imports or calls it.
    relations = resolve_fixture_repo()
    edge = one_tests_edge(relations, source="test_orders.test_total", target="orders.Order")
    assert edge.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC


def test_a_strict_edge_is_not_replaced_by_a_fixture_edge() -> None:
    # The test both imports+calls the target AND consumes a fixture reaching it.
    relations = resolve_strict_and_fixture_repo()
    edges = tests_edges(relations, source="test_orders.test_total", target="orders.Order")
    assert len(edges) == 1
    assert edges[0].derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC


def test_a_fixture_in_an_ancestor_conftest_resolves() -> None:
    relations = resolve_ancestor_conftest_repo()
    assert tests_edges(relations, source="tests.unit.test_orders.test_total", target="orders.Order")


def test_the_nearest_conftest_wins() -> None:
    # Two conftest.py files define `store`; the deeper one must be chosen.
    relations = resolve_shadowed_conftest_repo()
    edge = one_tests_edge(relations, source="tests.unit.test_orders.test_total", target="orders.Nearest")
    assert edge is not None


def test_an_unresolved_parameter_produces_no_edge_and_no_error() -> None:
    # A parameter naming no fixture in scope is ordinary — it may come from a
    # plugin. It is not a defect to report.
    relations = resolve_unknown_parameter_repo()
    assert tests_edges_from(relations, source="test_orders.test_total") == []
```

Build each `resolve_*_repo` helper from the file's existing fixture-construction style. Each returns the resolver's relation tuple.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_resolution.py -k fixture -v`
Expected: FAIL — no fixture-mediated edge exists.

- [ ] **Step 3: Implement**

Add to `src/codeatlas/extraction/resolution.py`:

```python
def _conftest_scope(index: _Index) -> dict[str, list[str]]:
    """Directory prefix -> file IDs of `conftest.py` files at that prefix.

    Keys are the containing directory of each conftest, normalized to use "/"
    and to be "" at the repository root.
    """
    scope: dict[str, list[str]] = {}
    for record in index.files_by_id.values():
        path = record.relative_path.replace("\\", "/")
        if path.rsplit("/", 1)[-1] != "conftest.py":
            continue
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        scope.setdefault(directory, []).append(record.file_id)
    for file_ids in scope.values():
        file_ids.sort()
    return scope


def _visible_fixture(
    name: str, test_file_id: str, index: _Index, conftests: dict[str, list[str]]
) -> SymbolRecord | None:
    """The fixture `name` refers to, searched own file then ancestor conftests.

    Scoping is deliberately partial: pytest also resolves fixtures through
    plugins, `usefixtures`, and dynamic registration, none of which are visible
    to static analysis. Partial scoping over-matches rather than under-matches,
    and over-matching at a derivation that cannot close a test gap is the safe
    direction to be wrong in.
    """
    own = index.name_in_file.get((test_file_id, name), ())
    for symbol in own:
        if symbol.kind is SymbolKind.FIXTURE:
            return symbol

    record = index.files_by_id.get(test_file_id)
    if record is None:
        return None
    path = record.relative_path.replace("\\", "/")
    directory = path.rsplit("/", 1)[0] if "/" in path else ""

    # Nearest ancestor wins, so walk from the test's own directory upward.
    while True:
        for file_id in conftests.get(directory, ()):
            for symbol in index.name_in_file.get((file_id, name), ()):
                if symbol.kind is SymbolKind.FIXTURE:
                    return symbol
        if directory == "":
            return None
        directory = directory.rsplit("/", 1)[0] if "/" in directory else ""


def _derive_fixture_test_edges(
    relations: Sequence[RelationRecord], index: _Index
) -> list[RelationRecord]:
    """Emit `TESTS` where a test consumes a fixture that reaches the target.

    The edge is `low_confidence_heuristic`: a fixture constructing an object is
    evidence that the test exercises it, but the test never names the target,
    so the link is inference rather than a statement the source makes.
    """
    existing = {
        (relation.source_symbol_id, relation.target_symbol_id)
        for relation in relations
        if relation.kind is RelationKind.TESTS
    }
    calls_by_source: dict[str, list[RelationRecord]] = {}
    for relation in relations:
        if (
            relation.kind is RelationKind.CALLS
            and relation.target_symbol_id is not None
        ):
            calls_by_source.setdefault(relation.source_symbol_id, []).append(relation)

    conftests = _conftest_scope(index)
    edges: list[RelationRecord] = []
    seen: set[tuple[str, str]] = set()
    for relation in relations:
        if relation.kind is not RelationKind.CONSUMES_FIXTURE:
            continue
        fixture = _visible_fixture(
            relation.target_hint, relation.file_id, index, conftests
        )
        if fixture is None:
            continue
        for call in calls_by_source.get(fixture.symbol_id, ()):
            target = call.target_symbol_id
            if target is None:
                continue
            target_file = index.files_by_id.get(index.file_of_symbol.get(target, ""))
            if (
                target_file is None
                or target_file.classification is FileClassification.TEST_CODE
            ):
                continue
            key = (relation.source_symbol_id, target)
            # A strict import-and-call edge already states this more strongly.
            if key in existing or key in seen:
                continue
            seen.add(key)
            edges.append(
                RelationRecord(
                    relation_id=build_relation_id(
                        relation.source_symbol_id,
                        RelationKind.TESTS.value,
                        f"fixture:{relation.target_hint}:{call.target_hint}",
                        relation.start_line,
                    ),
                    source_symbol_id=relation.source_symbol_id,
                    target_symbol_id=target,
                    file_id=relation.file_id,
                    kind=RelationKind.TESTS,
                    target_hint=call.target_hint,
                    resolution=ResolutionState.RESOLVED,
                    derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
                    confidence=_CONFIDENCE[Derivation.LOW_CONFIDENCE_HEURISTIC],
                    start_line=relation.start_line,
                    end_line=relation.end_line,
                    candidate_count=1,
                    # How this edge was derived, so a gap reason can name it
                    # without re-deriving. `_derive_document_edges` already uses
                    # `module_hint` this way (`DERIVED_HINT`).
                    module_hint=FIXTURE_HINT,
                )
            )
    return edges
```

Add the marker beside the existing `DERIVED_HINT` constant:

```python
FIXTURE_HINT: Final[str] = "derived:fixture"
HELPER_HINT: Final[str] = "derived:helper"
```

In `resolve`, after line 172:

```python
        relations.extend(_derive_fixture_test_edges(relations, index))
```

Order matters: it runs after `_derive_test_edges` so `existing` already contains every strict edge.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_resolution.py -v`
Expected: PASS.

- [ ] **Step 5: Mutation-check the precedence guard**

Temporarily delete the `if key in existing or key in seen: continue` line. Run `uv run pytest tests/unit/test_resolution.py -k strict -v` and confirm `test_a_strict_edge_is_not_replaced_by_a_fixture_edge` FAILS. Restore the line and confirm it passes again. A guard whose removal breaks no test is not tested.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/extraction/resolution.py tests/unit/test_resolution.py
git commit -m "feat: derive fixture-mediated TESTS edges at low confidence"
```

---

### Task 5: Helper-mediated `TESTS` derivation

**Files:**
- Modify: `src/codeatlas/extraction/resolution.py` (new `_derive_helper_test_edges`, called from `resolve` after Task 4's line)
- Test: `tests/unit/test_resolution.py`

**Interfaces:**
- Consumes: Task 4's `existing`-edge precedence convention.
- Produces: `_derive_helper_test_edges(relations: Sequence[RelationRecord], index: _Index) -> list[RelationRecord]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_helper_mediated_test_produces_a_weak_edge() -> None:
    # test_total -> _build (same test file) -> orders.Order
    relations = resolve_helper_repo()
    edge = one_tests_edge(relations, source="test_orders.test_total", target="orders.Order")
    assert edge.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC


def test_a_two_hop_helper_chain_produces_nothing() -> None:
    # test_total -> _outer -> _inner -> orders.Order. Depth is fixed at one
    # intermediate hop; two hops through shared utilities reaches most of a
    # codebase and would make the signal worthless.
    relations = resolve_two_hop_helper_repo()
    assert tests_edges(relations, source="test_orders.test_total", target="orders.Order") == []


def test_a_helper_outside_a_test_file_is_not_a_helper() -> None:
    # The intermediate must itself live in test code, or this is an ordinary
    # two-hop call chain through production code.
    relations = resolve_production_intermediate_repo()
    assert tests_edges(relations, source="test_orders.test_total", target="orders.Order") == []


def test_a_strict_edge_is_not_replaced_by_a_helper_edge() -> None:
    relations = resolve_strict_and_helper_repo()
    edges = tests_edges(relations, source="test_orders.test_total", target="orders.Order")
    assert len(edges) == 1
    assert edges[0].derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_resolution.py -k helper -v`
Expected: the first FAILS (no edge). The three negative tests pass already — keep them; they are the guards that make the positive case meaningful.

- [ ] **Step 3: Implement**

```python
def _derive_helper_test_edges(
    relations: Sequence[RelationRecord], index: _Index
) -> list[RelationRecord]:
    """Emit `TESTS` where a test calls a test helper that calls the target.

    Exactly one intermediate hop. Two hops through shared test utilities would
    reach a large fraction of any codebase, which makes the signal worthless
    rather than merely weak.
    """
    existing = {
        (relation.source_symbol_id, relation.target_symbol_id)
        for relation in relations
        if relation.kind is RelationKind.TESTS
    }
    calls_by_source: dict[str, list[RelationRecord]] = {}
    for relation in relations:
        if (
            relation.kind is RelationKind.CALLS
            and relation.target_symbol_id is not None
        ):
            calls_by_source.setdefault(relation.source_symbol_id, []).append(relation)

    def in_test_code(symbol_id: str) -> bool:
        record = index.files_by_id.get(index.file_of_symbol.get(symbol_id, ""))
        return (
            record is not None
            and record.classification is FileClassification.TEST_CODE
        )

    edges: list[RelationRecord] = []
    seen: set[tuple[str, str]] = set()
    for symbol in index.symbols_by_id.values():
        if symbol.kind is not SymbolKind.TEST:
            continue
        for first in calls_by_source.get(symbol.symbol_id, ()):
            helper_id = first.target_symbol_id
            if helper_id is None or not in_test_code(helper_id):
                continue
            for second in calls_by_source.get(helper_id, ()):
                target = second.target_symbol_id
                if target is None or in_test_code(target):
                    continue
                key = (symbol.symbol_id, target)
                if key in existing or key in seen:
                    continue
                seen.add(key)
                edges.append(
                    RelationRecord(
                        relation_id=build_relation_id(
                            symbol.symbol_id,
                            RelationKind.TESTS.value,
                            f"helper:{first.target_hint}:{second.target_hint}",
                            first.start_line,
                        ),
                        source_symbol_id=symbol.symbol_id,
                        target_symbol_id=target,
                        file_id=first.file_id,
                        kind=RelationKind.TESTS,
                        target_hint=second.target_hint,
                        resolution=ResolutionState.RESOLVED,
                        derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
                        confidence=_CONFIDENCE[Derivation.LOW_CONFIDENCE_HEURISTIC],
                        start_line=first.start_line,
                        end_line=first.end_line,
                        candidate_count=1,
                        module_hint=HELPER_HINT,
                    )
                )
    return edges
```

Iteration is over `index.symbols_by_id.values()`, whose insertion order is snapshot-stable, so output order is deterministic.

In `resolve`, immediately after the Task 4 line:

```python
        relations.extend(_derive_helper_test_edges(relations, index))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_resolution.py -v`
Expected: PASS.

- [ ] **Step 5: Mutation-check the depth limit**

Temporarily add a third hop to the implementation (walk `calls_by_source` once more from `target`). Confirm `test_a_two_hop_helper_chain_produces_nothing` FAILS. Revert and confirm it passes.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/extraction/resolution.py tests/unit/test_resolution.py
git commit -m "feat: derive helper-mediated TESTS edges at low confidence"
```

---

### Task 6: `TestGapReason` contract

**Files:**
- Modify: `src/codeatlas/contracts.py` (new enum + model, new field on `ChangeAnalysisReport` near line 502)
- Test: `tests/contract/test_change_contract.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `TestGapReasonCode` (StrEnum), `TestGapReason` (ContractModel with `qualified_name: NonEmptyText`, `reason: TestGapReasonCode`, `explanation: NonEmptyText`, `evidence_ids: list[NonEmptyText]`), and `ChangeAnalysisReport.test_gap_reasons: list[TestGapReason]`.

- [ ] **Step 1: Write the failing tests**

Add to the contract test module covering `ChangeAnalysisReport` (find it with `uv run pytest --collect-only tests/contract -q | grep -i change` if unsure).

```python
def test_test_gap_reasons_defaults_to_empty() -> None:
    report = minimal_change_report()
    assert report.test_gap_reasons == []


def test_test_gaps_is_still_a_list_of_plain_strings() -> None:
    # The existing field is unchanged. A Phase 4 client keeps working.
    report = minimal_change_report(test_gaps=["orders.total"])
    assert report.test_gaps == ["orders.total"]


def test_the_contract_version_is_unchanged_by_the_addition() -> None:
    assert minimal_change_report().contract_version == "1.1"


def test_a_reason_carries_its_supporting_evidence() -> None:
    reason = TestGapReason(
        qualified_name="orders.total",
        reason=TestGapReasonCode.FIXTURE_MEDIATED_ONLY,
        explanation="Reached only through fixture `store`.",
        evidence_ids=["ev-1"],
    )
    assert reason.evidence_ids == ["ev-1"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/contract -k gap_reason -v`
Expected: FAIL with `ImportError` / `AttributeError` — the names do not exist.

- [ ] **Step 3: Implement**

In `src/codeatlas/contracts.py`, above `ChangeAnalysisReport`:

```python
class TestGapReasonCode(StrEnum):
    """Why a changed symbol has no qualifying test edge.

    Every code describes a symbol that IS in `test_gaps`. A symbol whose kind is
    untestable is skipped before it can become a gap, so no code exists for it.
    """

    FIXTURE_MEDIATED_ONLY = "FIXTURE_MEDIATED_ONLY"
    HELPER_MEDIATED_ONLY = "HELPER_MEDIATED_ONLY"
    IMPORTED_NOT_CALLED = "IMPORTED_NOT_CALLED"
    CALLED_NOT_IMPORTED = "CALLED_NOT_IMPORTED"
    NO_TEST_FILE_REFERENCE = "NO_TEST_FILE_REFERENCE"


class TestGapReason(ContractModel):
    """One explanation for one entry in `test_gaps`.

    This never states that a symbol is untested. It states what CodeAtlas found
    and did not find in the relation graph, which is a different and smaller
    claim.
    """

    qualified_name: NonEmptyText
    reason: TestGapReasonCode
    explanation: NonEmptyText
    evidence_ids: list[NonEmptyText] = Field(default_factory=list)
```

On `ChangeAnalysisReport`, directly after `test_gaps` (line 502):

```python
    # Additive beside `test_gaps`, which keeps its type and meaning, so
    # `contract_version` stays "1.1" and a Phase 4 client is unaffected.
    test_gap_reasons: list[TestGapReason] = Field(default_factory=list)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/contract -v`
Expected: PASS. If a test asserts an exact field set on `ChangeAnalysisReport`, add `test_gap_reasons` to it.

- [ ] **Step 5: Regenerate the exported schema and the web types**

```bash
uv run python scripts/export_contract_schema.py
uv run pwsh -File scripts/generate_web_types.ps1
```

If either script name differs, find it under `scripts/` — do not hand-edit generated types (`documentation/rules.md`).

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/contracts.py docs/api/ apps/web/src/lib/ tests/contract/
git commit -m "feat: add additive test_gap_reasons to the change report"
```

---

### Task 7: Reasons in impact, weak edges in expansion

**Files:**
- Modify: `src/codeatlas/analysis/impact.py:459-487` (`_test_gaps`), its caller at line 273, and `_SYMMETRIC_KINDS` neighborhood for the `CONSUMES_FIXTURE` exclusion
- Modify: `src/codeatlas/analysis/engine.py` (populate `test_gap_reasons` on the report)
- Test: `tests/unit/test_impact.py`, `tests/integration/test_change_analysis.py`

**Interfaces:**
- Consumes: Tasks 4, 5 (weak edges), Task 6 (`TestGapReason`, `TestGapReasonCode`).
- Produces: `_test_gaps(...) -> tuple[tuple[str, ...], tuple[TestGapReason, ...]]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_fixture_mediated_symbol_stays_a_gap() -> None:
    # The governing principle: a weak edge explains a gap, it does not close it.
    gaps, _ = analyze_fixture_mediated()
    assert "orders.Order" in gaps


def test_a_fixture_mediated_gap_says_why() -> None:
    _, reasons = analyze_fixture_mediated()
    reason = by_name(reasons, "orders.Order")
    assert reason.reason is TestGapReasonCode.FIXTURE_MEDIATED_ONLY
    assert reason.evidence_ids != []


def test_a_strictly_tested_symbol_is_not_a_gap() -> None:
    gaps, reasons = analyze_strictly_tested()
    assert "orders.Order" not in gaps
    assert by_name(reasons, "orders.Order") is None


def test_an_unreferenced_symbol_reports_no_reference() -> None:
    _, reasons = analyze_unreferenced()
    reason = by_name(reasons, "orders.Order")
    assert reason.reason is TestGapReasonCode.NO_TEST_FILE_REFERENCE
    assert reason.evidence_ids == []


def test_an_imported_but_uncalled_symbol_says_so() -> None:
    _, reasons = analyze_imported_not_called()
    assert by_name(reasons, "orders.Order").reason is TestGapReasonCode.IMPORTED_NOT_CALLED


def test_fixture_mediation_outranks_import_without_call() -> None:
    # Precedence runs strongest near-miss first.
    _, reasons = analyze_fixture_and_bare_import()
    assert by_name(reasons, "orders.Order").reason is TestGapReasonCode.FIXTURE_MEDIATED_ONLY


def test_every_gap_has_exactly_one_reason() -> None:
    gaps, reasons = analyze_mixed()
    assert sorted(gaps) == sorted(reason.qualified_name for reason in reasons)


def test_a_weak_edge_appears_in_impact_with_its_derivation() -> None:
    edges = impact_edges_for_fixture_mediated()
    edge = one(edges, target="test_orders.test_total")
    assert edge.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC


def test_consumes_fixture_is_not_an_impact_edge() -> None:
    # It is an extraction intermediate, not a dependency.
    edges = impact_edges_for_fixture_mediated()
    assert all(edge.kind is not RelationKind.CONSUMES_FIXTURE for edge in edges)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_impact.py -k gap -v`
Expected: FAIL — `_test_gaps` returns a single tuple, so unpacking raises.

- [ ] **Step 3: Exclude `CONSUMES_FIXTURE` from expansion**

In `src/codeatlas/analysis/impact.py`, beside `_STRUCTURAL_KINDS`:

```python
# An extraction intermediate: it records which fixture a test asked for, not
# what depends on what. Following it would report a fixture name as blast
# radius.
_NON_IMPACT_KINDS: Final[frozenset[RelationKind]] = frozenset(
    {RelationKind.CONSUMES_FIXTURE}
)
```

Skip these in the expansion walk beside the existing `_STRUCTURAL_KINDS` check — read the walk and place the guard where structural kinds are already filtered.

- [ ] **Step 4: Rewrite `_test_gaps`**

```python
def _test_gaps(
    changes: Sequence[SymbolChange],
    target: GraphSide,
    ids: Mapping[str, str],
    adjacency: _Adjacency,
) -> tuple[tuple[str, ...], tuple[TestGapReason, ...]]:
    """Changed code symbols with no *qualifying* `TESTS` edge, and why.

    A qualifying edge is one the strict import-and-call pass produced. A
    fixture- or helper-mediated edge is reported as the reason the gap remains
    rather than as coverage that closes it: it is a candidate, and promoting a
    candidate to a fact is the one thing this product must not do.

    None of this claims a symbol is untested. Only executing the suite could.
    """
    gaps: list[str] = []
    reasons: list[TestGapReason] = []
    for change in changes:
        if change.symbol_kind in _UNTESTABLE_KINDS:
            continue
        if change.change_kind is ChangeKind.DELETED:
            continue
        symbol_id = ids.get(change.qualified_name)
        if symbol_id is None:
            continue
        if change.qualified_name in gaps:
            continue

        incoming = tuple(adjacency.by_target.get(symbol_id, ()))
        qualifying = [
            relation
            for relation in incoming
            if relation.kind is RelationKind.TESTS
            and relation.derivation is Derivation.HIGH_CONFIDENCE_HEURISTIC
        ]
        if qualifying:
            continue

        gaps.append(change.qualified_name)
        reasons.append(_gap_reason(change.qualified_name, incoming))
    order = sorted(range(len(gaps)), key=lambda position: gaps[position])
    return (
        tuple(gaps[position] for position in order),
        tuple(reasons[position] for position in order),
    )


def _gap_reason(
    qualified_name: str, incoming: Sequence[RelationRecord]
) -> TestGapReason:
    """The single strongest near-miss explaining one gap.

    Precedence runs from the strongest near-miss to the weakest, so the reason
    names the closest thing to coverage that was actually found.
    """
    weak = [
        relation
        for relation in incoming
        if relation.kind is RelationKind.TESTS
        and relation.derivation is Derivation.LOW_CONFIDENCE_HEURISTIC
    ]
    fixture = [item for item in weak if item.module_hint == FIXTURE_HINT]
    helper = [item for item in weak if item.module_hint == HELPER_HINT]
    imports = [
        relation for relation in incoming if relation.kind is RelationKind.IMPORTS
    ]
    calls = [relation for relation in incoming if relation.kind is RelationKind.CALLS]

    if fixture:
        chosen = fixture
        return TestGapReason(
            qualified_name=qualified_name,
            reason=TestGapReasonCode.FIXTURE_MEDIATED_ONLY,
            explanation=(
                "A test reaches this only through a fixture. That is a "
                "candidate, not coverage."
            ),
            evidence_ids=[relation.relation_id for relation in chosen],
        )
    if helper:
        return TestGapReason(
            qualified_name=qualified_name,
            reason=TestGapReasonCode.HELPER_MEDIATED_ONLY,
            explanation=(
                "A test reaches this only through a test helper. That is a "
                "candidate, not coverage."
            ),
            evidence_ids=[relation.relation_id for relation in helper],
        )
    if imports and not calls:
        return TestGapReason(
            qualified_name=qualified_name,
            reason=TestGapReasonCode.IMPORTED_NOT_CALLED,
            explanation="A test imports this but never calls it.",
            evidence_ids=[relation.relation_id for relation in imports],
        )
    if calls and not imports:
        return TestGapReason(
            qualified_name=qualified_name,
            reason=TestGapReasonCode.CALLED_NOT_IMPORTED,
            explanation=(
                "A test calls this name without importing it, so the call may "
                "resolve to a different symbol."
            ),
            evidence_ids=[relation.relation_id for relation in calls],
        )
    return TestGapReason(
        qualified_name=qualified_name,
        reason=TestGapReasonCode.NO_TEST_FILE_REFERENCE,
        explanation="No test file references this symbol.",
        evidence_ids=[],
    )
```

`FIXTURE_HINT` and `HELPER_HINT` are the `module_hint` markers set by Tasks 4 and 5. Import them from `codeatlas.extraction.resolution`. Matching on them rather than re-deriving means the reason cites the edge that actually exists.

Update the caller at line 273 to unpack both values and carry `test_gap_reasons` through, then populate the field on the report in `src/codeatlas/analysis/engine.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_impact.py tests/integration/test_change_analysis.py -v`
Expected: PASS.

- [ ] **Step 6: Mutation-check the governing principle**

Change the `qualifying` filter to accept any `TESTS` edge regardless of derivation. Confirm `test_a_fixture_mediated_symbol_stays_a_gap` FAILS. Revert and confirm it passes. This is the invariant the whole design rests on; if no test catches its removal, the design is not implemented.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/analysis/ tests/
git commit -m "feat: explain every test gap with its strongest near-miss"
```

---

### Task 8: Stale-resolver limitation

A `RESOLVER_VERSION` bump does not reindex anything. An existing snapshot keeps its old relations and will report gaps the new resolver would explain.

**Files:**
- Modify: `src/codeatlas/analysis/engine.py` (append to `report.limitations`)
- Test: `tests/integration/test_change_analysis.py`

**Interfaces:**
- Consumes: `RESOLVER_VERSION` from `codeatlas.extraction.resolution`; `Snapshot.resolver_version`.
- Produces: a limitation string on `ChangeAnalysisReport.limitations`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_stale_resolver_snapshot_reports_a_limitation() -> None:
    report = analyze_with_snapshot_resolver_version("1.1.0")
    assert any("older resolver" in item for item in report.limitations)


def test_a_current_resolver_snapshot_reports_no_such_limitation() -> None:
    report = analyze_with_snapshot_resolver_version(RESOLVER_VERSION)
    assert not any("older resolver" in item for item in report.limitations)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/integration/test_change_analysis.py -k resolver -v`
Expected: the first FAILS; the second passes vacuously.

- [ ] **Step 3: Implement**

In `src/codeatlas/analysis/engine.py`, where limitations are assembled:

```python
        if snapshot.resolver_version != RESOLVER_VERSION:
            # A resolver bump does not reindex. Until this repository is
            # reindexed, test-gap data came from the older derivation passes and
            # will overstate gaps. Reporting it without saying so is exactly the
            # failure this product exists to prevent.
            limitations.append(
                "Test-gap data was produced by an older resolver "
                f"({snapshot.resolver_version}; current is {RESOLVER_VERSION}) "
                "and may overstate gaps. Reindex this repository to refresh it."
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_change_analysis.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codeatlas/analysis/engine.py tests/integration/test_change_analysis.py
git commit -m "feat: report a limitation when the snapshot predates the resolver bump"
```

---

### Task 9: End-to-end integration over a realistic repository

Unit tests exercise each pass in isolation. This proves the pipeline works end to end with real SQLite, real parsing, and real indexing.

**Files:**
- Create: `tests/integration/test_fixture_test_mapping.py`
- Create fixture tree under the test's `tmp_path` (built in code, not committed as files)

**Interfaces:**
- Consumes: every prior task.
- Produces: nothing consumed later.

- [ ] **Step 1: Write the failing test**

Build a repository under `tmp_path` containing:

- `src/orders.py` — `class Order`, `def total(order)`, `def unused_helper()`
- `conftest.py` at the root — `@pytest.fixture def store(): return Order()`
- `tests/conftest.py` — `@pytest.fixture def clock(): return 0`
- `tests/test_orders.py` — `def test_total(store)` (fixture-mediated to `Order`); `def _build(): return total(...)` and `def test_via_helper(): _build()` (helper-mediated to `total`); `def test_direct()` importing and calling `unused_helper` directly (strict edge)

Register, index, and run a working-tree change analysis after editing all three source symbols. Assert:

```python
def test_the_pipeline_maps_fixtures_helpers_and_gaps(tmp_path: Path) -> None:
    report = index_and_analyze(tmp_path)
    reasons = {item.qualified_name: item.reason for item in report.test_gap_reasons}

    # Fixture-mediated: still a gap, explained.
    assert "orders.Order" in report.test_gaps
    assert reasons["orders.Order"] is TestGapReasonCode.FIXTURE_MEDIATED_ONLY

    # Helper-mediated: still a gap, explained.
    assert reasons["orders.total"] is TestGapReasonCode.HELPER_MEDIATED_ONLY

    # Strict import-and-call: not a gap at all.
    assert "orders.unused_helper" not in report.test_gaps

    # Every gap carries exactly one reason.
    assert sorted(report.test_gaps) == sorted(reasons)

    # The contract did not move.
    assert report.contract_version == "1.1"
```

Use real services throughout. Per `documentation/rules.md`, do not mock SQLite, parsers, or application services here.

- [ ] **Step 2: Run the test to verify it fails, then passes**

Run: `uv run pytest tests/integration/test_fixture_test_mapping.py -v`

If it fails after Tasks 1–8 are complete, the failure is real integration signal — debug it rather than adjusting the assertions to match current output.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. Note the total count; `documentation/memory.md` records 1926 passing as of 2026-08-06.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_fixture_test_mapping.py
git commit -m "test: end-to-end fixture and helper test mapping"
```

---

### Task 10: Quality gate, evaluation, ADR-0016, documentation

**Files:**
- Create: `docs/adr/0016-derivation-tiered-test-edges.md`
- Create: `docs/evaluation/test-mapping-2026-08-07.md` (name it for the date it is actually run)
- Modify: `docs/operations/change-analysis.md`, `documentation/architecture.md`, `documentation/memory.md`, `docs/plans/PLAN.md`
- Do **not** modify: `docs/evaluation/baseline-phase-4.*` or any Phase 4 gate artifact

- [ ] **Step 1: Run the full quality gate**

```bash
uv run ruff check src tests scripts
uv run mypy --no-incremental src
uv run pytest -q
```

Record each command, its exit code, and its output. Fix failures; do not skip or weaken a test to get green (`documentation/rules.md`).

- [ ] **Step 2: Re-run the evaluation**

```bash
uv run python scripts/run_evaluation.py
```

Check the script's actual flags with `--help` before running.

- [ ] **Step 3: Record the deltas honestly**

Write `docs/evaluation/test-mapping-2026-08-07.md` with the new numbers beside the Phase 4 baseline (changed-symbol recall 1.0000, direct-impact recall 1.0000, finding precision 1.0000 across 24 cases, unsupported-claim rate 0.0000, changed-symbol precision 0.9375) and explain every movement.

**If direct-impact precision dropped, report it as a finding.** Do not weaken the derivation passes until the number recovers. **If the unsupported-claim rate moved off 0.0000, stop** — a `low_confidence_heuristic` edge is a labeled candidate, not a claim, so any movement indicates a labeling defect that must be fixed rather than recorded.

The Phase 4 baseline files are not edited. They are gate evidence approved on 2026-07-27.

- [ ] **Step 4: Write ADR-0016**

Use `docs/adr/0000-template.md`. Cover:

1. `CONSUMES_FIXTURE` as an intermediate relation kind — stored and citable, excluded from impact expansion — and the accepted cost of a Python-test-framework concept in a language-neutral enum.
2. Derivation-tiered `TESTS` edges: one relation kind, different confidence by derivation path.
3. The governing principle: **a weak edge explains a gap rather than closing it.**

Note that it extends ADR-0004 rather than superseding it.

- [ ] **Step 5: Update the documentation**

- `docs/operations/change-analysis.md` — the new edges, the reason codes, and the reindex requirement.
- `documentation/architecture.md` — `CONSUMES_FIXTURE` in the data model; `SymbolKind.FIXTURE` now emitted.
- `documentation/memory.md` — append to Completed; record the evaluation deltas and anything surprising.
- `docs/plans/PLAN.md` — **append** a handoff entry. Never rewrite an earlier one.

- [ ] **Step 6: Commit**

```bash
git add docs/ documentation/
git commit -m "docs: ADR-0016 and evaluation record for derivation-tiered test edges"
```

---

## Notes for the implementer

**Test helper names in this plan are illustrative.** `parse_python`, `kind_of`, `fixture_references`, `resolve_*_repo`, `analyze_*`, `by_name`, and `one` describe what each helper must do. Each test file has its own established conventions — read the file first and follow what is there. The assertions are the contract; the helper names are not.

**Line numbers drift.** Every `path:line` reference was accurate at `07b3e9c`. If a line does not contain what this plan says it does, locate the construct by name.

**The one invariant that must not be compromised:** a `low_confidence_heuristic` `TESTS` edge appears in impact and never removes its symbol from `test_gaps`. Task 7 Step 6 mutation-checks it. If a later change makes that check inconvenient, the change is wrong, not the check.
