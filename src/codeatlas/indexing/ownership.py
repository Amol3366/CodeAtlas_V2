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

**Pid reuse is detected where the platform can answer.** A pid identifies a
slot, not a process, and the operating system reassigns it. The owner stamp
therefore also records the owner's *start time*, and a pid whose live process
started at a different moment is a reused slot whose real owner is gone —
recoverable, not protected. ``GetProcessTimes`` answers this on Windows and
``/proc/<pid>/stat`` on Linux, both reachable through facilities this module
already uses and neither needing a new dependency. macOS has no such source
and keeps the pid-only behaviour, as does any stamp written before
``started_at`` existed. Every unanswerable case leaves the run alone, because
guessing "dead" costs data while guessing "alive" costs only a delayed
cleanup.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
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
    """The owner stamp to record on a run this process is starting.

    ``started_at`` is omitted rather than stored as ``None`` when the platform
    cannot answer, so the stamp is shaped exactly as it was before this key
    existed and any reader parses it unchanged.
    """
    stamp: dict[str, Any] = {"pid": os.getpid(), "token": PROCESS_TOKEN}
    started_at = process_start_time(os.getpid())
    if started_at is not None:
        stamp["started_at"] = started_at
    return stamp


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
    if not process_is_alive(pid):
        return False

    # The pid exists. Whether it is the *same process* is a second question,
    # and only a stamp carrying a start time can answer it. A stamp without one
    # predates this check and keeps the behaviour it was written under.
    stamped = owner.get("started_at")
    if not isinstance(stamped, int):
        return True

    observed = process_start_time(pid)
    if observed is None:
        # Unknown, not dead. Guessing "dead" here would let one process heal
        # another's in-flight index — the corruption this module prevents.
        return True

    return observed == stamped


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


def process_start_time(pid: int) -> int | None:
    """An opaque value identifying a process *instance*, not a pid slot.

    A pid is reused. A pid together with the moment that process started is
    not, for any interval that matters here. Returns ``None`` when the
    platform or the handle cannot answer, which callers must read as
    "unknown" and never as "dead" — see `owner_is_live`.

    The value is comparable only against another reading from the same
    platform, which is all `owner_is_live` ever does with it. It is not a
    wall-clock time and must not be rendered as one.
    """
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return _windows_process_start_time(pid)
    if sys.platform.startswith("linux"):
        return _linux_process_start_time(pid)
    # macOS has no source for this without a new dependency, and Section 5
    # does not name it as a supported environment. `None` keeps the
    # pre-existing pid-only behaviour rather than guessing.
    return None


def _linux_process_start_time(pid: int) -> int | None:
    """Field 22 of ``/proc/<pid>/stat``, in clock ticks since boot.

    Parsed from the last ``)`` rather than by splitting the whole line: field
    2 is the executable name in parentheses and may itself contain spaces and
    parentheses, so a naive split mis-indexes every field after it.
    """
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None

    _, _, rest = raw.rpartition(")")
    fields = rest.split()
    # `rest` begins at field 3, so field 22 is index 19.
    if len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def _windows_process_start_time(pid: int) -> int | None:
    """The process creation ``FILETIME``, as one comparable integer.

    100-nanosecond intervals since 1601-01-01. Two processes sharing a pid
    cannot share this value unless they started within the same 100 ns, which
    the OS does not do — it does not reissue a pid that fast.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return None

    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not ok:
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


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
