"""Every expectation must name an identifier the engine can resolve.

This is the mechanical form of a rule three records arrived at by
investigation. ADR-0031 found q019 declaring `README.Health`, which names no
symbol — and because `expected_symbols[0]` is also the query the harness
issues, the engine was asked something unanswerable and its correct abstention
was scored as a miss. ADR-0035 found relation endpoints declared as bare module
names (`orders`, `client`, `service`) that likewise name nothing.

Both were found by reading output and following a hunch. This finds them by
construction.

**The rule is "resolvable by `SymbolStore.find_exact`", not "equals a
qualified_name".** That distinction matters and was got wrong once while
writing this: `find_exact` resolves through four tiers — qualified name, module-
qualified name, short name, then case-insensitively — so `orders` legitimately
resolves to `src.orders` via its short name. A validator demanding qualified
names would reject valid expectations and force a corpus edit that made nothing
more correct.

Using the engine's own resolver also keeps the rule honest as the resolver
evolves: an expectation is valid exactly when the engine can resolve it, by
definition rather than by a second implementation that could drift.

**What this does not check.** That a resolvable name is the *right* answer is
what the evaluation metrics are for. This only rejects references to things
that do not exist, which is the failure no metric can catch — q024 carried a
stale `README.Sample Service` through ADR-0031 precisely because its
`CONCEPTUAL` intent is unmeasured, so nothing scored it.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.contracts import RelationKind
from codeatlas.evaluation.dataset import Dataset, load_dataset
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.stores import FileStore, SnapshotStore, SymbolStore

DATASET_ROOT = Path("tests/evaluation/cases")

# "SOURCE KIND TARGET", where a name may contain spaces -- a document heading is
# a symbol ("Order flow"), so splitting on whitespace mis-parses one end. The
# relation kind is the only fixed token, so anchor on it.
_RELATION = re.compile(
    rf"^(?P<source>.+?) (?:{'|'.join(sorted(k.value for k in RelationKind))})"
    r" (?P<target>.+)$"
)


class _Resolver:
    """`find_exact` against each fixture's indexed snapshot."""

    def __init__(self, dataset: Dataset, stack: ExitStack) -> None:
        self._by_fixture: dict[str, tuple[SymbolStore, str]] = {}
        self._files_by_fixture: dict[str, frozenset[str]] = {}
        fixtures = {case.repository_fixture for case in dataset.query_cases}
        for fixture in sorted(fixtures):
            workspace = stack.enter_context(tempfile.TemporaryDirectory())
            connection = stack.enter_context(connect(Path(workspace) / "corpus.db"))
            apply_migrations(connection)
            services = build_services(connection)
            repository = services.registration.register(
                RegisterRepositoryRequest(
                    path=str((dataset.fixtures_root / fixture).resolve())
                )
            )
            services.indexing.index(repository.repository_id)
            snapshot = SnapshotStore(connection).get_active(repository.repository_id)
            assert snapshot is not None, f"{fixture} produced no active snapshot"
            self._by_fixture[fixture] = (SymbolStore(connection), snapshot.snapshot_id)
            self._files_by_fixture[fixture] = frozenset(
                record.relative_path
                for record in FileStore(connection).list_for_snapshot(
                    snapshot.snapshot_id
                )
            )

    def resolves(self, fixture: str, name: str) -> bool:
        store, snapshot_id = self._by_fixture[fixture]
        return bool(store.find_exact(snapshot_id, name, 1))

    def indexes(self, fixture: str, relative_path: str) -> bool:
        """Whether the fixture's active snapshot actually contains that file.

        **Indexed, not present on disk.** "Exists" would not have caught the
        defect this check was added for: `git_changes/target/processor.py` is
        on disk and readable, and is excluded from every index because
        `target/` is a build-output ignore default. A case declaring evidence
        there can never be satisfied, and nothing said so.
        """
        return relative_path in self._files_by_fixture[fixture]


@pytest.fixture(scope="module")
def corpus() -> Iterator[tuple[Dataset, _Resolver]]:
    """Indexed once for the module: six fixtures is seconds, per test is not."""
    dataset = load_dataset(DATASET_ROOT)
    with ExitStack() as stack:
        yield dataset, _Resolver(dataset, stack)


def test_every_expected_symbol_names_something(corpus) -> None:  # type: ignore[no-untyped-def]
    dataset, resolver = corpus
    unresolved = [
        f"{case.id} ({case.repository_fixture}): expected_symbols {name!r}"
        for case in dataset.query_cases
        for name in case.expected_symbols
        if not resolver.resolves(case.repository_fixture, name)
    ]

    assert not unresolved, "expectations naming no symbol:\n  " + "\n  ".join(
        unresolved
    )


def test_every_query_subject_names_something(corpus) -> None:  # type: ignore[no-untyped-def]
    """The one that would have caught q019 outright.

    `query_subject` — and `expected_symbols[0]` in its absence — is the term the
    harness asks the engine. A subject that resolves to nothing poses an
    unanswerable question and scores the engine's correct refusal as a miss.
    """
    dataset, resolver = corpus
    unresolved = [
        f"{case.id} ({case.repository_fixture}): query_subject {case.query_subject!r}"
        for case in dataset.query_cases
        if case.query_subject
        and not resolver.resolves(case.repository_fixture, case.query_subject)
    ]

    assert not unresolved, "unanswerable query subjects:\n  " + "\n  ".join(unresolved)


def test_every_relation_endpoint_names_something(corpus) -> None:  # type: ignore[no-untyped-def]
    """The one that would have caught ADR-0035's bare module names."""
    dataset, resolver = corpus
    problems: list[str] = []
    for case in dataset.query_cases:
        for relation in case.expected_relations:
            match = _RELATION.match(relation)
            if match is None:
                problems.append(f"{case.id}: unparseable relation {relation!r}")
                continue
            for end in ("source", "target"):
                name = match.group(end)
                if not resolver.resolves(case.repository_fixture, name):
                    problems.append(
                        f"{case.id} ({case.repository_fixture}): {end} {name!r}"
                        f" in {relation!r}"
                    )

    assert not problems, "relation endpoints naming no symbol:\n  " + "\n  ".join(
        problems
    )


def test_the_resolver_actually_rejects_something(corpus) -> None:  # type: ignore[no-untyped-def]
    """Mutation check, because the three tests above pass on a clean corpus.

    A validator that cannot fail is a comment. This asserts the resolver says no
    to a name that certainly does not exist — including one shaped like the real
    defects, a plausible qualification of a symbol that does exist.
    """
    _, resolver = corpus

    assert not resolver.resolves("docs_config", "README.Sample Service")
    assert not resolver.resolves("tsjs_app", "definitely_not_a_symbol")
    assert resolver.resolves("docs_config", "Sample Service")


def test_every_expected_evidence_file_is_indexed(corpus) -> None:  # type: ignore[no-untyped-def]
    """An expectation must cite a file the engine can actually reach.

    ADR-0036 asserted that expected *symbols* resolve. That guarantee never
    covered the evidence **file**, and the gap had teeth: q034 and q035 declared
    evidence in `git_changes/target/processor.py`, which is on disk, readable,
    and excluded from every index because `target/` is a build-output ignore
    default. Their recall was structurally 0 and always had been, while
    `find_exact` happily resolved `process` -- from `base/service.py`, the only
    side the index could see.

    So the check is **indexed in the fixture's active snapshot**, not "exists".
    The weaker form would have passed on the day it landed and proven nothing.
    """
    dataset, resolver = corpus
    missing = [
        f"{case.id} ({case.repository_fixture}): {item.file_path} is not indexed"
        for case in dataset.query_cases
        for item in case.expected_evidence
        if not resolver.indexes(case.repository_fixture, item.file_path)
    ]

    assert not missing, "expectations citing a file no index contains:\n  " + (
        "\n  ".join(missing)
    )
