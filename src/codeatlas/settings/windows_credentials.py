"""The Windows Credential Manager, reached through `ctypes`.

Imported only on Windows, by `default_credential_store()`. Kept in its own
module so the platform-specific structures never load on a platform that
cannot use them, and so the boundary in `credentials.py` stays readable.

`CRED_PERSIST_LOCAL_MACHINE` rather than `CRED_PERSIST_ENTERPRISE`: the
credential is scoped to this user on this machine and does not roam to other
machines on a domain profile. A key silently following a user onto a shared
machine is the outcome worth preventing.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

from codeatlas.domain.errors import CredentialWriteFailedError

CRED_TYPE_GENERIC: Final[int] = 1
CRED_PERSIST_LOCAL_MACHINE: Final[int] = 2
ERROR_NOT_FOUND: Final[int] = 1168

# Namespaced so the entry is identifiable in the Credential Manager UI and
# cannot collide with another application's generic credential.
TARGET_PREFIX: Final[str] = "CodeAtlas/"


class _CredentialAttribute(ctypes.Structure):
    _fields_ = (
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_byte)),
    )


class _Credential(ctypes.Structure):
    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_CredentialAttribute)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

_advapi32.CredWriteW.argtypes = (ctypes.POINTER(_Credential), wintypes.DWORD)
_advapi32.CredWriteW.restype = wintypes.BOOL

_advapi32.CredReadW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.POINTER(_Credential)),
)
_advapi32.CredReadW.restype = wintypes.BOOL

_advapi32.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
_advapi32.CredDeleteW.restype = wintypes.BOOL

_advapi32.CredFree.argtypes = (ctypes.c_void_p,)
_advapi32.CredFree.restype = None


def _target_name(name: str) -> str:
    return f"{TARGET_PREFIX}{name}"


class WindowsCredentialStore:
    """One named generic credential per `name`, scoped to the current user."""

    def is_available(self) -> bool:
        return True

    def get(self, name: str) -> str | None:
        pointer = ctypes.POINTER(_Credential)()
        ok = _advapi32.CredReadW(
            _target_name(name), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        )
        if not ok:
            # Absent is the common case and is not an error. Any other read
            # failure is also reported as "no key": a settings page that cannot
            # read the store should behave as though nothing is configured
            # rather than fail the whole request.
            return None
        try:
            blob = pointer.contents
            size = int(blob.CredentialBlobSize)
            if size == 0:
                return None
            raw = ctypes.string_at(blob.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            _advapi32.CredFree(pointer)

    def set(self, name: str, value: str) -> None:
        encoded = value.encode("utf-16-le")
        buffer = ctypes.create_string_buffer(encoded, len(encoded))

        credential = _Credential()
        credential.Flags = 0
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = _target_name(name)
        credential.Comment = "CodeAtlas provider credential"
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.AttributeCount = 0
        credential.Attributes = None
        credential.TargetAlias = None
        credential.UserName = None

        if not _advapi32.CredWriteW(ctypes.byref(credential), 0):
            # The OS error number, never the value that was being written.
            raise CredentialWriteFailedError(
                "The Windows Credential Manager rejected the write.",
                details={
                    "credential": name,
                    "os_error": str(ctypes.get_last_error()),
                },
            )

    def clear(self, name: str) -> None:
        if not _advapi32.CredDeleteW(_target_name(name), CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                # Already the desired state.
                return
            raise CredentialWriteFailedError(
                "The Windows Credential Manager rejected the delete.",
                details={
                    "credential": name,
                    "os_error": str(ctypes.get_last_error()),
                },
            )


__all__ = ["WindowsCredentialStore"]
