"""Read-only Git state capture.

Security rules for this module, which exist because Git is the one place where
CodeAtlas launches a process while holding untrusted repository paths:

* every invocation passes an argument array with ``shell=False`` — a command
  string is never constructed, so a repository name can never become an argument;
* the repository is selected with ``cwd``, never with a positional path, so a
  directory named like an option cannot be parsed as one;
* only read-only plumbing commands are used, with an explicit timeout;
* prompting and optional lock writes are disabled through the environment.

Every failure degrades to a :class:`GitState` carrying a warning code. Git being
absent, slow, or pointed at a non-repository is a normal condition for a
local-first product, not an error.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT_SECONDS: float = 10.0
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class GitState:
    """The Git facts a snapshot records, or the reason they are unavailable."""

    is_repository: bool
    head_commit: str | None
    branch: str | None
    is_dirty: bool
    warnings: tuple[str, ...]


class GitAdapter:
    """Reads Git state from a repository root without mutating it."""

    def __init__(
        self,
        git_executable: str = "git",
        timeout_seconds: float = GIT_TIMEOUT_SECONDS,
    ) -> None:
        self._git_executable = git_executable
        self._timeout_seconds = timeout_seconds

    def read_state(self, root: Path) -> GitState:
        """Return the Git state of ``root``, degrading with a warning code."""
        inside, failure = self._run(root, "rev-parse", "--is-inside-work-tree")
        if failure is not None:
            return _unavailable(failure)
        if inside is None or inside.strip() != "true":
            return _unavailable("GIT_NOT_A_REPOSITORY")

        # Git answers for the enclosing work tree, so a directory nested inside
        # someone else's repository would otherwise inherit that repository's
        # HEAD, branch, and dirty state. CodeAtlas will not attribute Git facts
        # it cannot scope to the registered root.
        toplevel, failure = self._run(root, "rev-parse", "--show-toplevel")
        if failure is not None:
            return _unavailable(failure)
        if toplevel is None or not _same_directory(toplevel.strip(), root):
            return _unavailable("GIT_ROOT_MISMATCH")

        warnings: list[str] = []

        head_commit, failure = self._run(root, "rev-parse", "--verify", "HEAD")
        if failure is not None:
            return _unavailable(failure)
        if head_commit is None:
            head_commit = None
            warnings.append("GIT_NO_COMMITS")
        elif not _COMMIT_PATTERN.match(head_commit.strip()):
            head_commit = None
            warnings.append("GIT_UNEXPECTED_OUTPUT")
        else:
            head_commit = head_commit.strip()

        branch, failure = self._run(root, "rev-parse", "--abbrev-ref", "HEAD")
        if failure is not None:
            return _unavailable(failure)
        branch_name = branch.strip() if branch else None

        status, failure = self._run(root, "status", "--porcelain=v1")
        if failure is not None:
            return _unavailable(failure)
        is_dirty = bool(status and status.strip())

        return GitState(
            is_repository=True,
            head_commit=head_commit,
            branch=branch_name,
            is_dirty=is_dirty,
            warnings=tuple(warnings),
        )

    def _run(self, root: Path, *arguments: str) -> tuple[str | None, str | None]:
        """Run one read-only Git command.

        Returns ``(stdout, None)`` on success, ``(None, None)`` when Git exited
        non-zero (an expected condition such as an unborn HEAD), and
        ``(None, warning_code)`` when Git could not be run at all.
        """
        try:
            # Fixed argument array, never a shell string.
            completed = subprocess.run(
                [self._git_executable, *arguments],
                cwd=str(root),
                shell=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env={
                    **os.environ,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_OPTIONAL_LOCKS": "0",
                },
            )
        except FileNotFoundError:
            return None, "GIT_EXECUTABLE_UNAVAILABLE"
        except subprocess.TimeoutExpired:
            return None, "GIT_TIMEOUT"
        except OSError:
            return None, "GIT_EXECUTABLE_UNAVAILABLE"

        if completed.returncode != 0:
            return None, None
        return completed.stdout, None


def _same_directory(reported: str, root: Path) -> bool:
    """Compare a Git-reported directory with the approved root."""
    if not reported:
        return False
    try:
        left = Path(os.path.realpath(reported))
        right = Path(os.path.realpath(root))
    except OSError:
        return False
    if os.name == "nt":
        return str(left).casefold() == str(right).casefold()
    return left == right


def _unavailable(warning_code: str) -> GitState:
    return GitState(
        is_repository=False,
        head_commit=None,
        branch=None,
        is_dirty=False,
        warnings=(warning_code,),
    )
