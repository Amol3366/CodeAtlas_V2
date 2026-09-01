"""Load and validate the versioned Phase 0 evaluation corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import Field, ValidationError, model_validator

from codeatlas.contracts import (
    ContractModel,
    NonEmptyText,
    OpaqueId,
    PositiveLine,
    RepositoryRelativePath,
)

DATASET_CONTRACT_VERSION: Literal["1.0"] = "1.0"
"""The evaluation corpus format version, deliberately independent of the API's
``CONTRACT_VERSION``.

They version different things. The API contract describes what a client
receives; this describes the shape of the gold corpus on disk. P6-STREAM moved
the API to 1.1, and letting that renumber the corpus would have invalidated
every tracked case file and every baseline for a change that touched neither.
"""


class DatasetError(ValueError):
    """The evaluation corpus is malformed or references invalid fixture data."""


class FixtureSnapshot(ContractModel):
    id: OpaqueId
    members: list[RepositoryRelativePath] = Field(min_length=1)


class FixtureDescriptor(ContractModel):
    id: OpaqueId
    root: RepositoryRelativePath
    kind: NonEmptyText
    snapshots: list[FixtureSnapshot] = Field(min_length=1)


class EvidenceExpectation(ContractModel):
    evidence_id: OpaqueId
    snapshot_id: OpaqueId
    file_path: RepositoryRelativePath
    symbol: NonEmptyText | None = None
    start_line: PositiveLine
    end_line: PositiveLine
    validated_line_count: int = Field(default=0, exclude=True, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> EvidenceExpectation:
        if self.end_line < self.start_line:
            raise ValueError("evidence end_line must not precede start_line")
        return self


class QueryCase(ContractModel):
    id: OpaqueId
    repository_fixture: OpaqueId
    snapshot_id: OpaqueId
    question: NonEmptyText
    intent: NonEmptyText
    expected_abstention: bool
    # What the question is *about*, when that differs from what it expects back.
    # `expected_symbols` is the answer, and for a graph query the subject is not
    # in it: "Who calls total?" expects `render` and is about `total`. Absent
    # means the subject is `expected_symbols[0]`, which is true for every exact,
    # lexical, and self-referential case. Optional so the 40 existing cases stay
    # valid unchanged; declaring it is additive, never a re-labelling of an
    # expectation (ADR-0003).
    query_subject: NonEmptyText | None = None
    # How far the traversal runs for this case (ADR-0073 ruling 3).
    #
    # Depth used to be implied: `GraphQueryRequest.max_depth` defaults to 2 and
    # every graph case silently took it, while ADR-0059 ruled that an
    # expectation declares *direct* results. A case therefore declared depth-1
    # answers and was scored against a depth-2 traversal, and the undeclared
    # second-hop results read as distractors -- which is the whole reason q003,
    # q005, q015 and q053 are reversal-sensitive.
    #
    # Making it explicit does not change any answer: every graph case declares
    # **2**, the value it was already getting. That is deliberate. The
    # measurement says all 31 satisfy their declared relations at depth 1, but
    # dropping to 1 would remove the depth-2 distractors and with them the
    # ranking sensitivity ADR-0059 kept on purpose, turning
    # `exact_symbol_resolution` from a ranking gate back into a resolution one.
    # ADR-0073 says ruling 3 *extends* ADR-0059; that would overturn it. So the
    # field is introduced with today's value, and any retuning is a separate
    # decision with its own measurement.
    #
    # Required for graph intents and forbidden elsewhere -- see the validator.
    traversal_depth: int | None = Field(default=None, ge=1, le=5)
    expected_symbols: list[NonEmptyText]
    expected_relations: list[NonEmptyText]
    expected_evidence: list[EvidenceExpectation]
    warnings: list[str]
    limitations: list[str]
    forbidden_claims: list[NonEmptyText]

    @model_validator(mode="after")
    def _depth_belongs_to_graph_cases(self) -> QueryCase:
        """A graph case declares its depth; a non-graph case has none to declare.

        Both directions are enforced, because a silently-ignored field is worse
        than a missing one: a `traversal_depth` on an `EXACT_SYMBOL` case would
        read as though it controlled something, and nothing would contradict it.
        That is the shape ADR-0053 recorded, where a constant nobody checked
        removed a case from a denominator without saying so.
        """
        if self.intent in GRAPH_INTENTS and self.traversal_depth is None:
            raise ValueError(
                f"case {self.id}: intent {self.intent} traverses relations and "
                "must declare traversal_depth (ADR-0073 ruling 3)"
            )
        if self.intent not in GRAPH_INTENTS and self.traversal_depth is not None:
            raise ValueError(
                f"case {self.id}: intent {self.intent} does not traverse "
                "relations, so traversal_depth would have no effect"
            )
        return self


class StateSpec(ContractModel):
    """One side of a change case, resolved to concrete directories.

    A state is ``root`` with ``overlay`` written over it: the overlay holds
    only the files that differ, and an empty overlay file means the file is
    absent on this side. ``label_prefix`` is the path prefix the corpus uses
    when it names this side's files (the `git_changes` fixture keeps both of
    its sides as subdirectories of one root and labels files `base/...` and
    `target/...`); an empty prefix means corpus paths are state-root-relative.
    """

    root: Path
    overlay: Path | None = None
    label_prefix: str = ""


class ChangeCase(ContractModel):
    id: OpaqueId
    repository_fixture: OpaqueId
    snapshot_id: OpaqueId
    base_ref: NonEmptyText
    target_ref: NonEmptyText
    expected_symbols: list[NonEmptyText]
    expected_relations: list[NonEmptyText]
    expected_evidence: list[EvidenceExpectation]
    expected_changed_symbols: list[NonEmptyText]
    expected_impact_paths: list[list[NonEmptyText]]
    expected_findings: list[NonEmptyText]
    # Which `StateView` reads the base side.
    #
    # `directory` compares two materialized directories, which is what every
    # case did until now and what keeps a case independent of Git being
    # installed. `git_blob` commits the base and reads it back through
    # `GitBlobStateView`, the view a real working-tree preflight uses.
    #
    # The distinction is not cosmetic: **the corpus could not express an
    # ADR-0044-shaped defect at all** while both sides were directories. That
    # record fixed the blob view to apply the same ignore rules as a scan, and a
    # directory-versus-directory case cannot see it -- both sides apply those
    # rules already, so a tracked-but-ignored file is absent from *both* and a
    # case asserting "no deletion" passes with the fix and without it. Permanent
    # green reads as coverage, which is why no such case was committed before
    # the harness could run this side through Git.
    base_view: Literal["directory", "git_blob"] = "directory"
    warnings: list[str]
    limitations: list[str]
    forbidden_claims: list[NonEmptyText]
    base_state: StateSpec = Field(
        default_factory=lambda: StateSpec(root=Path(".")), exclude=True
    )
    target_state: StateSpec = Field(
        default_factory=lambda: StateSpec(root=Path(".")), exclude=True
    )


# The corpus intent vocabulary, grouped by what a correct answer *is*.
#
# A symbol-shaped question has one right symbol, so top-1 is the honest measure.
# A lexical question ("which config key sets the port") is answered by matching
# text, and scoring it as a top-1 *symbol* result asks a different question than
# the one posed. Keeping the two apart is why `exact_symbol_resolution` and
# `lexical_resolution` are separate metrics (ADR-0023).
#
# Defined here, in the corpus contract, so the adapter and the runner cannot
# hold two definitions that drift apart.
SYMBOL_INTENTS: Final[frozenset[str]] = frozenset(
    {
        "EXACT_SYMBOL",
        "CALLERS",
        "DEPENDENCIES",
        "EXPORTS",
        "RELATED_TESTS",
        "TRACE_FLOW",
    }
)
LEXICAL_INTENTS: Final[frozenset[str]] = frozenset(
    {"CONFIG_LOOKUP", "DOCUMENT_LOOKUP"}
)
# The intents answered by traversing stored relations, and therefore the ones
# whose answer depends on how far the traversal runs. `EXACT_SYMBOL` is a
# symbol intent but not a graph one: it resolves a name and never walks an edge.
#
# Defined here beside the other corpus vocabulary for ADR-0023's reason -- the
# adapter maps these to service methods and would otherwise hold a second
# definition that could drift. `test_engine_adapter.py` pins the two together.
GRAPH_INTENTS: Final[frozenset[str]] = SYMBOL_INTENTS - {"EXACT_SYMBOL"}

# Which gate table a corpus is measured by. `retrieval` is the default so every
# existing manifest stays valid unchanged; the conceptual corpus declares its
# own, because top-1 and exact-span rules describe an instrument it is not.
TargetProfile = Literal["retrieval", "conceptual"]


class DatasetManifest(ContractModel):
    contract_version: Literal["1.0"] = DATASET_CONTRACT_VERSION
    fixtures_root: RepositoryRelativePath
    variants_root: RepositoryRelativePath = "variants"
    fixtures: list[FixtureDescriptor] = Field(min_length=1)
    query_cases_file: RepositoryRelativePath
    change_cases_file: RepositoryRelativePath
    expected_query_count: Annotated[int, Field(ge=1)]
    expected_change_count: Annotated[int, Field(ge=1)]
    target_profile: TargetProfile = "retrieval"


class QueryCaseFile(ContractModel):
    contract_version: Literal["1.0"] = DATASET_CONTRACT_VERSION
    cases: list[QueryCase]


class ChangeCaseFile(ContractModel):
    contract_version: Literal["1.0"] = DATASET_CONTRACT_VERSION
    cases: list[ChangeCase]


class Dataset(ContractModel):
    contract_version: Literal["1.0"] = DATASET_CONTRACT_VERSION
    target_profile: TargetProfile = "retrieval"
    fixtures_root: Path
    fixtures: list[FixtureDescriptor]
    query_cases: list[QueryCase]
    change_cases: list[ChangeCase]


def load_dataset(dataset_root: Path) -> Dataset:
    """Load a dataset and validate every evidence location without imports."""
    try:
        root = dataset_root.resolve(strict=True)
        manifest = DatasetManifest.model_validate(
            _read_json(root / "dataset.json")
        )
        query_file = QueryCaseFile.model_validate(
            _read_json(_resolve_inside(root, manifest.query_cases_file))
        )
        change_file = ChangeCaseFile.model_validate(
            _read_json(_resolve_inside(root, manifest.change_cases_file))
        )
        _validate_unique_ids(
            [case.id for case in query_file.cases], "query case IDs"
        )
        _validate_unique_ids(
            [case.id for case in change_file.cases], "change case IDs"
        )
        if len(query_file.cases) != manifest.expected_query_count:
            raise DatasetError(
                "query case count does not match expected_query_count"
            )
        if len(change_file.cases) != manifest.expected_change_count:
            raise DatasetError(
                "change case count does not match expected_change_count"
            )

        fixtures_root = _resolve_inside(root, manifest.fixtures_root)
        variants_root = _resolve_inside(
            root, manifest.variants_root, must_exist=False
        )
        fixtures = {fixture.id: fixture for fixture in manifest.fixtures}
        if len(fixtures) != len(manifest.fixtures):
            raise DatasetError("fixture IDs must be unique")
        fixture_roots = {
            fixture_id: _resolve_inside(fixtures_root, fixture.root)
            for fixture_id, fixture in fixtures.items()
        }
        if any(not fixture_root.is_dir() for fixture_root in fixture_roots.values()):
            raise DatasetError("every fixture root must be a directory")
        snapshot_membership = {
            fixture.id: {
                snapshot.id: set(snapshot.members)
                for snapshot in fixture.snapshots
            }
            for fixture in manifest.fixtures
        }
        if any(
            len(snapshots) != len(fixture.snapshots)
            for fixture, snapshots in (
                (fixture, snapshot_membership[fixture.id])
                for fixture in manifest.fixtures
            )
        ):
            raise DatasetError("fixture snapshot IDs must be unique")

        queries = [
            case.model_copy(
                update={
                    "expected_evidence": _validate_evidence(
                        case.repository_fixture,
                        case.expected_evidence,
                        fixture_roots,
                        snapshot_membership,
                    )
                }
            )
            for case in query_file.cases
        ]
        changes = [
            case.model_copy(
                update=_prepare_change_case(
                    case, fixture_roots, variants_root, snapshot_membership
                )
            )
            for case in change_file.cases
        ]
        return Dataset(
            target_profile=manifest.target_profile,
            fixtures_root=fixtures_root,
            fixtures=manifest.fixtures,
            query_cases=queries,
            change_cases=changes,
        )
    except DatasetError:
        raise
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise DatasetError(str(exc)) from exc


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _resolve_inside(
    root: Path, relative_path: str, *, must_exist: bool = True
) -> Path:
    resolved_root = root.resolve(strict=True)
    candidate = (resolved_root / relative_path).resolve(strict=must_exist)
    if not candidate.is_relative_to(resolved_root):
        raise DatasetError("path must remain repository-relative")
    return candidate


def _validate_unique_ids(ids: list[str], label: str) -> None:
    if len(ids) != len(set(ids)):
        raise DatasetError(f"{label} must be unique")


def _prepare_change_case(
    case: ChangeCase,
    fixture_roots: dict[str, Path],
    variants_root: Path,
    snapshot_membership: dict[str, dict[str, set[str]]],
) -> dict[str, object]:
    fixture_root = fixture_roots[case.repository_fixture]
    base_state, target_state = _resolve_state_specs(
        case.repository_fixture,
        case.base_ref,
        case.target_ref,
        fixture_root,
        variants_root,
    )
    validated = _validate_evidence(
        case.repository_fixture,
        case.expected_evidence,
        fixture_roots,
        snapshot_membership,
        base_state=base_state,
        target_state=target_state,
        is_change_case=True,
    )
    return {
        "base_state": base_state,
        "target_state": target_state,
        "expected_evidence": validated,
    }


def _validate_evidence(
    fixture_id: str,
    evidence: list[EvidenceExpectation],
    fixture_roots: dict[str, Path],
    snapshot_membership: dict[str, dict[str, set[str]]],
    *,
    base_state: StateSpec | None = None,
    target_state: StateSpec | None = None,
    is_change_case: bool = False,
) -> list[EvidenceExpectation]:
    if fixture_id not in fixture_roots:
        raise DatasetError(f"unknown repository fixture: {fixture_id}")
    fixture_root = fixture_roots[fixture_id]
    fallback = StateSpec(root=fixture_root)
    effective_base = base_state or fallback
    effective_target = target_state or fallback
    validated: list[EvidenceExpectation] = []
    evidence_ids = [item.evidence_id for item in evidence]
    _validate_unique_ids(evidence_ids, "evidence IDs")
    for item in evidence:
        if not is_change_case:
            members = snapshot_membership[fixture_id].get(item.snapshot_id)
            if members is None or item.file_path not in members:
                raise DatasetError(
                    "evidence does not belong to declared snapshot membership"
                )
        side_is_base = item.snapshot_id.endswith("-base")
        spec = effective_base if side_is_base else effective_target
        source_path = _resolve_state_file(spec, item.file_path)
        if source_path is None:
            raise DatasetError(f"evidence is not a file: {item.file_path}")
        line_count = len(
            source_path.read_text(encoding="utf-8").splitlines()
        )
        if item.end_line > line_count:
            raise DatasetError(
                f"evidence line range exceeds {item.file_path}: "
                f"{item.end_line} > {line_count}"
            )
        validated.append(
            item.model_copy(update={"validated_line_count": line_count})
        )
    return validated


def _resolve_state_file(spec: StateSpec, file_path: str) -> Path | None:
    """Locate a corpus-labeled file inside one resolved state.

    Mirrors materialization exactly: the label prefix is stripped, the overlay
    wins over the root, and an empty overlay file means the file does not
    exist on this side. Every lookup stays containment-checked.
    """
    relative_path = file_path
    if spec.label_prefix and relative_path.startswith(spec.label_prefix):
        relative_path = relative_path[len(spec.label_prefix) :]
    if spec.overlay is not None:
        candidate = _resolve_inside(
            spec.overlay, relative_path, must_exist=False
        )
        if candidate.is_file():
            if candidate.stat().st_size == 0:
                return None
            return candidate
    try:
        resolved = _resolve_inside(spec.root, relative_path)
    except FileNotFoundError:
        return None
    return resolved if resolved.is_file() else None


def _resolve_state_specs(
    fixture_id: str,
    base_ref: str,
    target_ref: str,
    fixture_root: Path,
    variants_root: Path,
) -> tuple[StateSpec, StateSpec]:
    """Resolve both sides of a case together, per decision 12.

    The grammar is pairwise on purpose. A ``working-tree:<slug>`` target
    describes an *edited copy of the base state*, so it owns both sides: the
    base side takes the slug's ``base/`` overlay when one exists (else the base
    ref resolves alone), and the target side starts from the base side's root —
    not the fixture root — so a case whose base ref selects a side directory
    (`git_changes` c023) edits that directory rather than the merged fixture.
    Resolving each ref independently is the defect that made every
    ``base/``-overlay case compare two identical states.
    """
    base = _resolve_side(fixture_id, base_ref, fixture_root, variants_root, "base")

    if target_ref.startswith("working-tree:"):
        slug = target_ref[len("working-tree:") :]
        slug_root = variants_root / fixture_id / slug
        if base.overlay is None and (slug_root / "base").is_dir():
            base = StateSpec(
                root=base.root,
                overlay=slug_root / "base",
                label_prefix=base.label_prefix,
            )
        target_overlay = slug_root / "target"
        target = StateSpec(
            root=base.root,
            overlay=target_overlay if target_overlay.is_dir() else None,
            label_prefix=base.label_prefix,
        )
        return base, target

    target = _resolve_side(
        fixture_id, target_ref, fixture_root, variants_root, "target"
    )
    return base, target


def _resolve_side(
    fixture_id: str,
    ref: str,
    fixture_root: Path,
    variants_root: Path,
    side: Literal["base", "target"],
) -> StateSpec:
    """Map one state reference to the directories that realize it.

    Supported grammar:
    - ``HEAD`` → the fixture root (committed baseline), no overlay.
    - ``base`` / ``target`` → that subdirectory of the fixture root, *selected*
      as the state root with the directory name as the corpus label prefix;
      the fixture root itself when the subdirectory is absent.
    - ``working-tree:<slug>`` → the fixture root plus the slug's ``<side>/``
      overlay when it exists. (As a target ref this is re-based onto the base
      side's root by :func:`_resolve_state_specs`.)
    - ``<name>:<slug>`` → the ``<name>`` subdirectory of the fixture root plus
      the ``variants/<fixture>/<name>-<slug>/<name>`` overlay when it exists.
    """
    if ref == "HEAD":
        return StateSpec(root=fixture_root)

    if ref in {"base", "target"}:
        candidate = fixture_root / ref
        if candidate.is_dir():
            return StateSpec(root=candidate, label_prefix=f"{ref}/")
        return StateSpec(root=fixture_root)

    fixture_variants = variants_root / fixture_id
    if ref.startswith("working-tree:"):
        slug = ref[len("working-tree:") :]
        overlay = fixture_variants / slug / side
        return StateSpec(
            root=fixture_root,
            overlay=overlay if overlay.is_dir() else None,
        )

    if ":" in ref:
        name, slug = ref.split(":", 1)
        overlay = fixture_variants / f"{name}-{slug}" / name
        resolved_overlay = overlay if overlay.is_dir() else None
        named_root = fixture_root / name
        if named_root.is_dir():
            return StateSpec(
                root=named_root,
                overlay=resolved_overlay,
                label_prefix=f"{name}/",
            )
        return StateSpec(root=fixture_root, overlay=resolved_overlay)

    raise DatasetError(f"unrecognized state ref: {ref}")
