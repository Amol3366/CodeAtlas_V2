"""A PowerShell script is never invoked with array splatting.

PowerShell has two splatting forms and they do different things. Splatting a
**hashtable** passes *named* parameters. Splatting an **array** passes
*positional* arguments -- and a `[switch]` parameter is never positional, so an
array splat into a switch-only script fails to bind every argument with
``PositionalParameterNotFound``.

`check_phase7.ps1` did exactly that. Its packaging step built an array so that
`-SemanticLocal` and `-SkipZip` could be added conditionally, then splatted it
into `build_package.ps1`, whose parameters are all switches. **The `-Package`
path could never have run**, and nothing noticed because that path is slow and
optional and therefore rarely exercised -- `documentation/memory.md` had already
recorded that `check_phase7.ps1` "is the one that goes unrun".

`check_phase6.ps1` passes the same switch literally and works, which is what
makes this a regression rather than a latent flaw in both.

The confusable case, deliberately allowed: `Invoke-Checked` array-splats into
`uv`. Splatting an array into a **native executable** is correct -- the elements
become raw argv strings and no parameter binder is involved. So the rule is not
"never array-splat", it is "never array-splat into a PowerShell script".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS = Path("scripts")

# `& (Join-Path ...) @name` or `& $path @name` -- an ampersand call whose target
# ends in .ps1 (or is built by Join-Path from a .ps1 literal) followed by an
# array-splatted variable.
_SPLAT_CALL = re.compile(
    r"&\s*(?P<target>\([^)]*\.ps1[^)]*\)|\$\w+)\s+@(?P<var>\w+)",
    re.IGNORECASE,
)


def _powershell_scripts() -> list[Path]:
    found = sorted(SCRIPTS.glob("*.ps1"))
    assert found, "no PowerShell scripts found; the guard would pass vacuously"
    return found


@pytest.mark.parametrize(
    "script", _powershell_scripts(), ids=lambda p: p.name
)
def test_no_powershell_script_is_called_with_array_splatting(
    script: Path,
) -> None:
    """Catch the binding failure statically, because running it is expensive.

    Proving this dynamically means a full PyInstaller build per gate script.
    The static form runs in milliseconds and fails for the same reason.
    """
    text = script.read_text(encoding="utf-8")
    offenders = [
        match.group(0)
        for match in _SPLAT_CALL.finditer(text)
        # A hashtable splat is written the same way at the call site, so the
        # declaration is what distinguishes them. Only flag a variable that is
        # assigned an @( ... ) array literal somewhere in the file.
        if re.search(
            rf"\${match.group('var')}\s*=\s*@\(", text
        )
    ]

    assert not offenders, (
        f"{script.name} array-splats into a PowerShell script: {offenders}. "
        "Array splatting binds positionally and a [switch] is never "
        "positional, so every argument fails to bind. Use a hashtable splat "
        "(@{ Name = $true }) or pass the switches literally."
    )


# --- The packaging script bundles what the parsers read -----------------------
#
# A second class of packaging defect, caught the same way and for the same
# reason: statically, because proving it dynamically costs a PyInstaller build.
#
# ADR-0065's parsers read two kinds of file that are *data* rather than modules
# -- each grammar's own `queries/tags.scm`, and the `*.imports.scm` authored in
# this repository. PyInstaller finds the modules by analysis, since the imports
# are static, and never the data.
#
# Omitting them does not degrade the build, it destroys it. `build_registry()`
# constructs every parser eagerly, so on 2026-08-19 the packaged artifact died
# on the first command that built services -- `repo add` and `doctor` both
# raised `FileNotFoundError: tree_sitter_java ships no tags.scm`, and only
# `--help` survived.
#
# `test_the_packaged_build_parses_a_query_backed_language` covers this too, but
# it needs a built artifact and therefore only runs behind the opt-in `-Package`
# flag -- the same flag that went unrun through four ADR-0065 slices and let the
# defect reach `main`. These tests need no build and run in every gate.

_LANGUAGES = Path("src/codeatlas/parsing/query_backed/languages")
_BUILD_SCRIPT = SCRIPTS / "build_package.ps1"
_SPEC = Path("packaging/codeatlas.spec")

# `load_tags_source("tree_sitter_java")` -- the grammar package whose shipped
# data the adapter reads.
_TAGS_SOURCE = re.compile(r"load_tags_source\(\s*[\"'](?P<module>[\w.]+)[\"']")
# `load_query_source("java.imports.scm")` -- a query authored in this repository.
_QUERY_SOURCE = re.compile(r"load_query_source\(\s*[\"'](?P<name>[\w.]+)[\"']")


def _adapter_sources() -> list[Path]:
    """Every language adapter, found by glob rather than by a list.

    A list would have to be extended for a new language, which is the exact
    failure this test exists to catch -- one level up.
    """
    return sorted(
        path for path in _LANGUAGES.glob("*.py") if path.name != "__init__.py"
    )


def test_every_grammar_whose_data_is_read_is_collected_by_the_build() -> None:
    """A grammar's `tags.scm` must be bundled, or the artifact cannot start.

    Derived from the adapters rather than from a constant: whatever they pass to
    `load_tags_source` is what has to exist on disk at runtime, so a language
    added without a matching `--collect-data` fails here in milliseconds instead
    of in a user's first command.
    """
    # Read from the SPEC since 2026-09-04, when the build became spec-driven so
    # it could produce two executables. The requirement is unchanged and the
    # derivation below is unchanged; only the file carrying the collection
    # moved. **Both files are searched**, so this keeps passing whichever one
    # holds it -- a guard that breaks on a refactor it should not care about is
    # a guard people delete.
    script = _BUILD_SCRIPT.read_text(encoding="utf-8")
    if _SPEC.exists():
        script += "\n" + _SPEC.read_text(encoding="utf-8")

    collected = set(re.findall(r'"--collect-data",\s*"?(?P<m>[\w.]+)"?', script))
    collected |= set(re.findall(r'"(tree_sitter_\w+)"', script))

    assert "collect_data_files" in script or "--collect-data" in script, (
        "neither the build script nor the spec collects any package data. "
        "Naming a grammar is not bundling its tags.scm."
    )

    required = {
        match.group("module")
        for path in _adapter_sources()
        for match in _TAGS_SOURCE.finditer(path.read_text(encoding="utf-8"))
    }
    assert required, "no adapter reads a grammar tags.scm; the regex is stale"

    missing = sorted(required - collected)
    assert not missing, (
        f"{_BUILD_SCRIPT.name} does not bundle grammar data for {missing}. "
        "PyInstaller finds the module by analysis and never its data files, so "
        "the packaged build raises FileNotFoundError on the first command that "
        "constructs parsers. Add --collect-data for each."
    )


def test_the_authored_import_queries_are_added_to_the_build() -> None:
    """The `*.imports.scm` written in this repository must be bundled too.

    This is the omission that surfaced *behind* the grammar one on 2026-08-19:
    fixing the first revealed the second, because they fail at different points
    in the same constructor.
    """
    script = _BUILD_SCRIPT.read_text(encoding="utf-8")
    if _SPEC.exists():
        script += "\n" + _SPEC.read_text(encoding="utf-8")
    authored = {
        match.group("name")
        for path in _adapter_sources()
        for match in _QUERY_SOURCE.finditer(path.read_text(encoding="utf-8"))
    }
    assert authored, "no adapter reads an authored query; the regex is stale"

    # The whole directory is carried in one entry, so the check is that the
    # directory is bundled -- not that each file is named.
    #
    # **Matched against the bundling, never against the path string.** A first
    # version asserted only that "query_backed/queries" appeared somewhere in
    # the script, and it passed with the `--add-data` line deleted: the
    # `$importQueries = Join-Path ...` definition contains the same substring.
    # Mutation caught that, and the distinction survives the 2026-09-04 move to
    # a spec -- where the path is now handed over as an environment variable,
    # so the chain has two links and both are checked.
    flattened = script.replace("\\", "/")
    bundled = re.search(
        r'"--add-data"\s*,\s*"[^"]*query_backed/queries"', flattened
    ) or re.search(
        r'CODEATLAS_BUILD_QUERIES"\]\s*,\s*"codeatlas/parsing/query_backed/queries"',
        flattened,
    )
    assert bundled, (
        "the build does not bundle the authored query directory, but the "
        f"adapters load {sorted(authored)} from it relative to __file__. "
        "Defining the path is not bundling it."
    )

    if _SPEC.exists():
        assert "$env:CODEATLAS_BUILD_QUERIES" in _BUILD_SCRIPT.read_text(
            encoding="utf-8"
        ), (
            "the spec bundles CODEATLAS_BUILD_QUERIES but "
            f"{_BUILD_SCRIPT.name} never sets it, so the build would carry an "
            "empty source path -- the second link in the chain."
        )
