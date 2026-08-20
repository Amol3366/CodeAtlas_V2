"""Every tracked text file keeps LF in the working tree, not just the corpus.

`.gitattributes` declares `* text=auto eol=lf` for the whole repository, and
`tests/evaluation/test_dataset.py` enforces it -- **for three corpus
directories**. The product was never covered, which is why 18 files drifted to
CRLF without anything failing. This is the sibling guard that closes it.

**Why `git status` cannot tell you.** `text=auto` normalises on read, so Git
compares LF against LF and reports a clean tree while the bytes on disk have
CRLF. The drift is invisible to the tool everyone checks, which is exactly how
it survived: staging a CRLF file shows a plain `A`, with the endings mentioned
only in a warning nobody keeps. `git ls-files --eol` reports the working tree
separately from the index and is the cheap way to see it.

**Why the scope comes from Git rather than a list of directories.** This project
keeps finding one defect: a list that must be extended when something is added,
and which nothing enforces, is eventually wrong. `SUPPORTED_FIXTURES`, the
findings and impact `ROWS` tables, the PyInstaller data list and `README.md`
have each failed that way -- the third of those shipped a binary that could not
run at all. A guard hard-coding "check `src`, `tests`, `scripts`, `apps`" would
join them the first time a directory is added, so the set checked here is
whatever Git tracks. A new directory is covered the day it is committed, with
nobody having to remember.

The two assertions below are deliberately different questions: one asks whether
any file *has* drifted, the other whether anything is *permitted* to. A file
marked `-text` while still holding LF passes the first and fails the second,
which is the state a silencer would sit in before its bytes ever changed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# ADR-0043: preflight called every line of every file while `git status` was
# empty, because a checkout had rewritten the endings. The corpus could not
# reproduce it -- `eol=lf` means both sides agree -- so this file's raw bytes
# are the test. `tests/evaluation/test_dataset.py` pins that it keeps them.
CRLF_EXEMPTION = (
    "tests/evaluation/cases/variants/python_app/crlf-only/target/"
    "src/payments/service.py"
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_files() -> dict[str, tuple[str, str]]:
    """Map every tracked path to its working-tree endings and its attributes.

    `git ls-files --eol` prints `i/<index>  w/<worktree>  attr/<attrs>\tpath`.
    Only the `w/` half answers the first question: the index is normalised by
    definition, so reading it would report every file clean and assert nothing.
    """
    completed = subprocess.run(
        ["git", "ls-files", "--eol"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    tracked = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        fields, _, path = line.partition("\t")
        worktree = next(f for f in fields.split() if f.startswith("w/"))
        attrs = fields.partition("attr/")[2].strip()
        tracked[path] = (worktree.removeprefix("w/"), attrs)
    return tracked


def test_no_tracked_file_carries_crlf_into_the_working_tree() -> None:
    """The whole repository, not the three corpus directories.

    A product source file with CRLF is not cosmetic here: the change engine
    hashes bytes and diffs lines, so every line of it differs and every symbol
    in it reports as changed. `baseline-phase-7` recorded
    `changed_symbol_precision` 0.2000 from exactly one such file; the true value
    was 1.0000.

    The one skipped path is hard-coded rather than read from the `-text`
    attribute, so editing `.gitattributes` cannot silence this.
    """
    offenders = sorted(
        path
        for path, (worktree, _) in _tracked_files().items()
        if worktree in {"crlf", "mixed"} and path != CRLF_EXEMPTION
    )

    assert offenders == [], (
        f"{len(offenders)} tracked file(s) hold CRLF in the working tree while "
        "`.gitattributes` declares `* text=auto eol=lf`. `git status` will look "
        "clean, because `text=auto` normalises on read. Rewrite them with LF; "
        "note that `git checkout --` has twice reverted a fix along with the "
        f"thing it was meant to undo (ADR-0022, ADR-0042). Offenders: {offenders}"
    )


def test_only_the_file_adr_0043_argued_for_is_exempt_from_normalisation() -> None:
    """Nothing else may opt out of `eol=lf`, whatever its bytes say today.

    `-text` is the switch that turns the guard above off for a path. Checking it
    separately catches a silencer *before* any CRLF appears -- a file marked
    `-text` while still holding LF is invisible to the first assertion and is
    one commit away from being invisible for good.

    ADR-0043's fixture is the sole justified exemption because its raw bytes are
    what it measures. A second one needs its own record, not a quiet line in
    `.gitattributes`.

    **Declared binaries are outside the question.** `*.db`, `*.png` and the rest
    are marked `binary`, which expands to `-text -diff`, so they carry `-text`
    legitimately -- `tests/fixtures/upgrade/schema_0008.db` is one. Git reports
    those as `w/-text`, having no line endings to speak of, so they drop out
    here without anyone maintaining a list of extensions. The residual: marking
    a *source* path `binary` would hide it from both assertions. That is a far
    louder edit than adding `-text`, and it is stated rather than guarded.
    """
    exempt = sorted(
        path
        for path, (worktree, attrs) in _tracked_files().items()
        if "-text" in attrs.split() and worktree in {"lf", "crlf", "mixed"}
    )

    assert exempt == [CRLF_EXEMPTION], (
        "the set of paths exempt from `eol=lf` changed. Exactly one is expected. "
        f"Found: {exempt}"
    )
