"""Architecture rules: forbidden edges, declared in the repository.

A rule file is repository content and therefore untrusted input. It is parsed
with the standard library's ``tomllib``, validated field by field, bounded in
count, and rejected outright on anything unexpected — an unknown key is an
error, not something to ignore, because silently skipping a misspelled field
would leave a rule the author believes is enforced doing nothing.

TOML rather than the blueprint's YAML example: Phase 2 deliberately kept a YAML
dependency out of the tree, and adding one for a single trusted-path config file
would repeat the decision that was already made and rejected. The rule
*semantics* are the blueprint's. ADR-0005 records the deviation.

Only *new* violations are reported. A repository adopting rules mid-life has
existing violations, and reporting them on every change would bury the one edge
this change actually introduced. Newness is decided by relation identity: an
edge whose ``relation_id`` is absent from the base graph is new, which is exact
rather than a similarity guess.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from codeatlas.analysis.findings import ArchitectureViolation
from codeatlas.analysis.impact import GraphSide
from codeatlas.contracts import RelationKind, Severity
from codeatlas.domain.errors import AnalysisRulesInvalidError
from codeatlas.domain.relations import ResolutionState

RULES_RELATIVE_PATH: Final[str] = ".codeatlas/rules.toml"

MAX_RULES: Final[int] = 200
MAX_GLOB_LENGTH: Final[int] = 200
MAX_RULE_FILE_BYTES: Final[int] = 100_000

_ALLOWED_RULE_KEYS: Final[frozenset[str]] = frozenset(
    {"id", "description", "source_glob", "forbidden_target_glob", "relations",
     "severity"}
)
_RULE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ArchitectureRule:
    """One forbidden-relation rule."""

    rule_id: str
    description: str
    source_glob: str
    forbidden_target_glob: str
    relations: tuple[RelationKind, ...]
    severity: Severity


def load_rules(root: Path) -> tuple[ArchitectureRule, ...]:
    """Read and validate ``.codeatlas/rules.toml``, or return nothing.

    A missing file is not an error: most repositories have no rules, and
    demanding one would make the feature opt-out rather than opt-in.
    """
    path = root / RULES_RELATIVE_PATH
    if not path.is_file():
        return ()
    if path.stat().st_size > MAX_RULE_FILE_BYTES:
        raise AnalysisRulesInvalidError(
            "The architecture rule file exceeds the maximum readable size."
        )
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise AnalysisRulesInvalidError(
            "The architecture rule file is not valid TOML."
        ) from error
    return parse_rules(document)


def parse_rules(document: Mapping[str, Any]) -> tuple[ArchitectureRule, ...]:
    """Validate a parsed rule document into rules, or refuse it."""
    raw = document.get("rules", [])
    if not isinstance(raw, list):
        raise AnalysisRulesInvalidError("`rules` must be an array of tables.")
    if len(raw) > MAX_RULES:
        raise AnalysisRulesInvalidError(
            f"The rule file declares more than {MAX_RULES} rules."
        )

    rules: list[ArchitectureRule] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise AnalysisRulesInvalidError("Each rule must be a table.")
        unknown = set(entry) - _ALLOWED_RULE_KEYS
        if unknown:
            # Refused rather than ignored: a misspelled key would otherwise
            # leave the author believing a rule is enforced when it is not.
            raise AnalysisRulesInvalidError(
                f"Unknown rule field(s): {', '.join(sorted(unknown))}."
            )
        rule = _rule(entry)
        if rule.rule_id in seen:
            raise AnalysisRulesInvalidError(
                f"Duplicate rule id: {rule.rule_id}."
            )
        seen.add(rule.rule_id)
        rules.append(rule)
    return tuple(rules)


def _rule(entry: Mapping[str, Any]) -> ArchitectureRule:
    rule_id = entry.get("id")
    if not isinstance(rule_id, str) or not _RULE_ID.match(rule_id):
        raise AnalysisRulesInvalidError("Each rule needs a simple string `id`.")

    globs: dict[str, str] = {}
    for field_name in ("source_glob", "forbidden_target_glob"):
        value = entry.get(field_name)
        if not isinstance(value, str) or not value:
            raise AnalysisRulesInvalidError(
                f"Rule {rule_id} needs a non-empty `{field_name}`."
            )
        if len(value) > MAX_GLOB_LENGTH:
            raise AnalysisRulesInvalidError(
                f"Rule {rule_id} has an oversized `{field_name}`."
            )
        _compile_glob(value, rule_id)
        globs[field_name] = value

    relations = entry.get("relations", ["IMPORTS", "CALLS"])
    if not isinstance(relations, list) or not relations:
        raise AnalysisRulesInvalidError(
            f"Rule {rule_id} needs a non-empty `relations` array."
        )
    kinds: list[RelationKind] = []
    for value in relations:
        try:
            kinds.append(RelationKind(value))
        except ValueError as error:
            raise AnalysisRulesInvalidError(
                f"Rule {rule_id} names an unknown relation: {value!r}."
            ) from error

    severity_value = entry.get("severity", "high")
    try:
        severity = Severity(severity_value)
    except ValueError as error:
        raise AnalysisRulesInvalidError(
            f"Rule {rule_id} names an unknown severity: {severity_value!r}."
        ) from error

    description = entry.get("description", "")
    if not isinstance(description, str):
        raise AnalysisRulesInvalidError(
            f"Rule {rule_id} has a non-string `description`."
        )

    return ArchitectureRule(
        rule_id=rule_id,
        description=description or f"{rule_id} forbids this dependency.",
        source_glob=globs["source_glob"],
        forbidden_target_glob=globs["forbidden_target_glob"],
        relations=tuple(kinds),
        severity=severity,
    )


def evaluate_rules(
    rules: Sequence[ArchitectureRule],
    *,
    base: GraphSide,
    target: GraphSide,
) -> tuple[ArchitectureViolation, ...]:
    """Report forbidden edges the target state introduced.

    An edge already present in the base state is not reported. The comparison is
    on ``relation_id``, which encodes the source symbol, the kind, the target
    name, and the call site — so moving a forbidden call to a new line reports
    it again, and that is correct: it is a new call site.
    """
    if not rules:
        return ()

    existing = {
        relation.relation_id
        for relation in base.relations
        if relation.resolution is ResolutionState.RESOLVED
    }
    files = {symbol_id: _path(target, symbol_id) for symbol_id in target.symbols}

    violations: list[ArchitectureViolation] = []
    for relation in target.relations:
        if relation.resolution is not ResolutionState.RESOLVED:
            continue
        if relation.relation_id in existing:
            continue
        target_id = relation.target_symbol_id
        if target_id is None:
            continue
        source_path = files.get(relation.source_symbol_id)
        target_path = files.get(target_id)
        if source_path is None or target_path is None:
            continue

        for rule in rules:
            if relation.kind not in rule.relations:
                continue
            if not _matches(rule.source_glob, source_path):
                continue
            if not _matches(rule.forbidden_target_glob, target_path):
                continue
            violations.append(
                ArchitectureViolation(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    source=_name(target, relation.source_symbol_id),
                    target=_name(target, target_id),
                    kind=relation.kind,
                    description=rule.description,
                )
            )
    violations.sort(key=lambda item: (item.rule_id, item.source, item.target))
    return tuple(violations)


def _matches(glob: str, path: str) -> bool:
    return _compile_glob(glob, "").match(path) is not None


def _compile_glob(glob: str, rule_id: str) -> re.Pattern[str]:
    """Translate a path glob supporting ``**`` into a regular expression.

    The ignore-rule subset deliberately lacks ``**``, and architecture rules
    genuinely need it: a layer rule is about a directory tree, not one level of
    it. Translating here keeps that need local instead of widening a matcher
    other code depends on.
    """
    parts: list[str] = []
    index = 0
    while index < len(glob):
        character = glob[index]
        if glob.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif glob.startswith("**", index):
            parts.append(".*")
            index += 2
        elif character == "*":
            parts.append("[^/]*")
            index += 1
        elif character == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(character))
            index += 1
    try:
        return re.compile(f"^{''.join(parts)}$")
    except re.error as error:  # pragma: no cover - guarded by escaping above
        raise AnalysisRulesInvalidError(
            f"Rule {rule_id} has an unusable glob."
        ) from error


def _path(side: GraphSide, symbol_id: str) -> str | None:
    """The repository-relative path a symbol lives in, or ``None`` if unknown.

    A rule matches paths, so a symbol whose file is not in the mapping cannot be
    judged. Returning ``None`` skips it rather than matching it against a file
    ID, which would silently compare a rule to an opaque hash.
    """
    symbol = side.symbols.get(symbol_id)
    if symbol is None:
        return None
    return side.file_paths.get(symbol.file_id)


def _name(side: GraphSide, symbol_id: str) -> str:
    symbol = side.symbols.get(symbol_id)
    return symbol.qualified_name if symbol is not None else symbol_id
