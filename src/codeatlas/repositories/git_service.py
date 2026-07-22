"""Local Git state and rename-aware diffs (Blueprint §3.10, §4.3.1).

Uses the Git CLI via ``subprocess`` — read-only plumbing commands only
(``rev-parse``, ``status``, ``diff``). These never run repository hooks or
repository code (CLAUDE.md §2.4). Non-Git directories are fully supported: every
method degrades to an empty / non-git result rather than raising.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

_GIT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class GitState:
    """Current Git state of a repository root."""

    is_git_repository: bool
    branch: str | None = None  # None when detached HEAD
    commit_sha: str | None = None  # None when there are no commits yet (unborn HEAD)
    is_dirty: bool = False


@dataclass(frozen=True)
class GitChange:
    """One entry from a name-status diff. ``old_path`` is set only for renames/copies."""

    status: str  # "A", "M", "D", "R", "C", "T", ...
    path: str
    old_path: str | None = None
    similarity: int | None = None  # rename/copy similarity percentage when reported


def _run_git(root: str, args: list[str]) -> tuple[int, str, str]:
    """Run ``git <args>`` in ``root``. Returns (returncode, stdout, stderr).

    A missing Git binary yields returncode 127 rather than raising.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return 127, "", "git not found"
    except (subprocess.TimeoutExpired, OSError) as exc:  # pragma: no cover - environment guard
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


class GitService:
    """Read-only Git operations over a repository root path."""

    def get_state(self, root: str) -> GitState:
        code, out, _ = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
        if code != 0 or out.strip() != "true":
            return GitState(is_git_repository=False)

        branch = self._current_branch(root)
        commit = self._current_commit(root)
        dirty = self._is_dirty(root)
        return GitState(
            is_git_repository=True,
            branch=branch,
            commit_sha=commit,
            is_dirty=dirty,
        )

    def _current_branch(self, root: str) -> str | None:
        code, out, _ = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0:
            return None
        name = out.strip()
        return None if name in {"", "HEAD"} else name

    def _current_commit(self, root: str) -> str | None:
        code, out, _ = _run_git(root, ["rev-parse", "HEAD"])
        if code != 0:
            return None  # unborn HEAD (no commits yet)
        return out.strip() or None

    def _is_dirty(self, root: str) -> bool:
        code, out, _ = _run_git(root, ["status", "--porcelain"])
        if code != 0:
            return False
        return bool(out.strip())

    def diff_name_status(self, root: str, base: str, target: str | None = None) -> list[GitChange]:
        """Rename-aware name-status diff (``-M``).

        ``target=None`` compares ``base`` against the working tree. Returns an
        empty list for non-Git directories or an invalid ref.
        """
        args = ["diff", "--name-status", "-M", base]
        if target is not None:
            args.append(target)
        code, out, _ = _run_git(root, args)
        if code != 0:
            return []
        return _parse_name_status(out)


def _parse_name_status(output: str) -> list[GitChange]:
    changes: list[GitChange] = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t")
        code = fields[0]
        letter = code[0]
        similarity: int | None = None
        if letter in {"R", "C"} and len(code) > 1 and code[1:].isdigit():
            similarity = int(code[1:])
        if letter in {"R", "C"} and len(fields) >= 3:
            changes.append(
                GitChange(
                    status=letter,
                    path=fields[2],
                    old_path=fields[1],
                    similarity=similarity,
                )
            )
        elif len(fields) >= 2:
            changes.append(GitChange(status=letter, path=fields[1]))
    return changes
