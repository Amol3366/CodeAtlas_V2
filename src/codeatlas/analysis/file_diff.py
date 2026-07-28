"""File-level diff between two :class:`StateView`s.

The diff is deterministic: two files are the same when their content hashes are
identical. A rename is reported only when a deleted path and an added path share
an identical hash; anything else is a delete plus an add. This keeps the engine
from claiming a similarity-based rename it could not prove.
"""

from __future__ import annotations

from codeatlas.analysis.states import StateView
from codeatlas.contracts import FileChangeKind
from codeatlas.domain.change import FileChange


def compute_file_changes(
    base: StateView,
    target: StateView,
) -> tuple[FileChange, ...]:
    """Return added, deleted, modified, and renamed files between two states.

    Files whose content hashes match are omitted. A rename is emitted only when
    a deleted path and an added path share the same hash uniquely; non-unique
    matches are left as delete plus add.
    """
    base_files = {file.relative_path: file for file in base.list_files()}
    target_files = {file.relative_path: file for file in target.list_files()}

    base_paths = set(base_files)
    target_paths = set(target_files)

    changes: list[FileChange] = []

    for path in sorted(base_paths & target_paths):
        base_file = base_files[path]
        target_file = target_files[path]
        if base_file.content_hash != target_file.content_hash:
            changes.append(
                FileChange(
                    path=path,
                    kind=FileChangeKind.MODIFIED,
                    content_hash_changed=True,
                )
            )

    added_paths = sorted(target_paths - base_paths)
    deleted_paths = sorted(base_paths - target_paths)

    added_by_hash: dict[str, list[str]] = {}
    for path in added_paths:
        added_by_hash.setdefault(target_files[path].content_hash, []).append(path)

    deleted_by_hash: dict[str, list[str]] = {}
    for path in deleted_paths:
        deleted_by_hash.setdefault(base_files[path].content_hash, []).append(path)

    used_added: set[str] = set()
    used_deleted: set[str] = set()

    for content_hash in sorted(set(added_by_hash) & set(deleted_by_hash)):
        added_list = added_by_hash[content_hash]
        deleted_list = deleted_by_hash[content_hash]
        # A deterministic rename requires a unique pair on both sides.
        if len(added_list) != 1 or len(deleted_list) != 1:
            continue
        added_path = added_list[0]
        deleted_path = deleted_list[0]
        changes.append(
            FileChange(
                path=added_path,
                kind=FileChangeKind.RENAMED,
                base_path=deleted_path,
                content_hash_changed=False,
            )
        )
        used_added.add(added_path)
        used_deleted.add(deleted_path)

    for path in deleted_paths:
        if path not in used_deleted:
            changes.append(
                FileChange(
                    path=path,
                    kind=FileChangeKind.DELETED,
                    content_hash_changed=True,
                )
            )

    for path in added_paths:
        if path not in used_added:
            changes.append(
                FileChange(
                    path=path,
                    kind=FileChangeKind.ADDED,
                    content_hash_changed=True,
                )
            )

    changes.sort(key=lambda change: change.path)
    return tuple(changes)
