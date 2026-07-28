"""Who owns an in-flight index run, and whether that owner still exists.

Recovery heals what a crashed process left behind. To do that safely it has to
answer one question first: **is the process that started this run still
running?** Healing a run whose owner is alive is not recovery, it is
corruption — and the opportunity is real, because recovery runs inside
`build_services`, which is per request, while the watcher indexes on a
background thread.

Two signals answer it, cheapest first.

* ``PROCESS_TOKEN`` identifies *this* process. A run stamped with it belongs to
  a thread in this very process, so it is alive by construction — no system
  call, no ambiguity. This covers the common case: the watcher indexing while a
  request arrives.
* ``process_is_alive`` answers for every other token, which means a different
  CodeAtlas process — a ``codeatlas index`` run in a terminal while the API
  serves. Conservative on purpose: an owner that still exists is left alone.

A run with no owner recorded at all is treated as unowned, and therefore
recoverable. That is the honest reading — nobody is claiming it — and it is
what lets a database written by an older version, before ownership existed, be
healed on upgrade rather than staying blocked forever.

**Known limitation: pid reuse.** If the operating system reassigns a dead
owner's pid before CodeAtlas next starts, its run looks alive and is left
alone. The failure is visible rather than silent — ``codeatlas doctor`` reports
the blocking run and the pid it belongs to — but it is not detected
automatically. Closing it needs the owner's process start time, which has no
portable source without a new dependency.
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any

# Regenerated on every import, and therefore once per process. Two processes
# cannot collide, and — unlike a pid — it is never reused.
PROCESS_TOKEN: str = uuid.uuid4().hex

# Windows constants, named rather than inlined so the calls below read.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_INVALID_PARAMETER = 87
_ERROR_ACCESS_DENIED = 5


def current_owner() -> dict[str, Any]:
    """The owner stamp to record on a run this process is starting."""
    return {"pid": os.getpid(), "token": PROCESS_TOKEN}


def owner_is_live(owner: Any) -> bool:
    """Whether the recorded owner of a run is still running.

    ``owner`` comes from stored JSON, so it is whatever was written — possibly
    nothing, possibly a shape from another version. Anything unreadable is
    treated as unowned, which makes the run recoverable.
    """
    if not isinstance(owner, dict):
        return False

    if owner.get("token") == PROCESS_TOKEN:
        # This process. Alive by construction: the code asking is running.
        return True

    pid = owner.get("pid")
    if not isinstance(pid, int):
        return False
    return process_is_alive(pid)


def process_is_alive(pid: int) -> bool:
    """Whether a process with this pid currently exists.

    Returns ``True`` when the answer cannot be established, because the caller
    uses this to decide whether to overwrite someone else's work. Guessing
    "dead" there loses data; guessing "alive" only delays a cleanup.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_process_is_alive(pid)
    return _posix_process_is_alive(pid)


def _posix_process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists; this user may not signal it.
        return True
    except OSError:
        return True
    return True


def _windows_process_is_alive(pid: int) -> bool:
    """Ask the Win32 API directly.

    ``os.kill`` is not usable here: on Windows Python implements it with
    ``TerminateProcess`` for any signal other than the console control events,
    so the POSIX idiom ``os.kill(pid, 0)`` would **kill the process** it was
    meant to ask about.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        error = ctypes.get_last_error()
        if error == _ERROR_INVALID_PARAMETER:
            return False  # No such process.
        if error == _ERROR_ACCESS_DENIED:
            return True  # It exists; this token may not query it.
        return True  # Unknown failure: assume alive and leave the run alone.

    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        # A process that exited with 259 is indistinguishable from a running
        # one by this API. Erring toward "alive" is the safe direction.
        return bool(code.value == _STILL_ACTIVE)
    finally:
        kernel32.CloseHandle(handle)
