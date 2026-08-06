"""Where the OpenAI API key lives, and the one place it is resolved.

A credential is the one piece of state CodeAtlas holds that cannot be
un-disclosed. `.env` works, but it is a plaintext file inside a project
folder: it gets committed, copied, zipped, and screen-shared. This module
gives the key somewhere better on Windows and keeps `.env` as a fallback.

Two rules carry the module, and both are tested rather than trusted:

**A resolved key is never written back into `os.environ`.** CodeAtlas invokes
Git through a subprocess adapter, and a child process inherits its parent's
environment. Publishing the key process-wide would hand it to every Git call
for the life of the server. `load_env_file` already does this for the `.env`
path, which is a pre-existing weakness this module must not extend.

**An unavailable store refuses writes.** Reporting success while storing
nothing would tell a user their key is safe when it is not stored at all.
"""

from __future__ import annotations

import sys
from typing import Final, Protocol

from codeatlas.domain.errors import CredentialStoreUnavailableError

OPENAI_CREDENTIAL_NAME: Final[str] = "OPENAI_API_KEY"


class CredentialStore(Protocol):
    """A place to keep one named secret.

    Narrow on purpose (`AGENTS.md` Section 4.5): the platform API behind it is
    substitutable, and the application layer never learns which one it got.
    """

    def is_available(self) -> bool:
        """Whether this store can hold anything on this machine."""

    def get(self, name: str) -> str | None:
        """The stored value, or ``None`` when absent or unreadable."""

    def set(self, name: str, value: str) -> None:
        """Store ``value``, replacing any existing entry."""

    def clear(self, name: str) -> None:
        """Remove the entry. Absent is success, not an error."""


class UnavailableCredentialStore:
    """The store on a platform that has none.

    Windows 11 is the primary supported environment (Section 5), so this is a
    normal state rather than a failure: reads return nothing and `.env`
    supplies the key instead.
    """

    def is_available(self) -> bool:
        return False

    def get(self, name: str) -> str | None:
        return None

    def set(self, name: str, value: str) -> None:
        raise CredentialStoreUnavailableError(
            "This platform has no credential store. Set the key in .env instead.",
            details={"credential": name},
        )

    def clear(self, name: str) -> None:
        # Idempotent, and the desired end state already holds.
        return None


def default_credential_store() -> CredentialStore:
    """The store for this platform.

    Selected by platform rather than by trying and catching, so a settings page
    can report availability without attempting a write.
    """
    if sys.platform == "win32":
        from codeatlas.settings.windows_credentials import WindowsCredentialStore

        return WindowsCredentialStore()
    return UnavailableCredentialStore()


def resolve_openai_api_key(store: CredentialStore | None = None) -> str | None:
    """The OpenAI API key, from the credential store or `.env`, in that order.

    The single place any caller learns the key. Four call sites used to read
    `os.environ` directly, and four readers means four chances for one to miss
    a new source.

    The return value is handed to the caller that needs it and is deliberately
    *not* written back into `os.environ`: see the module docstring.
    """
    import os

    resolved = store if store is not None else default_credential_store()

    stored = resolved.get(OPENAI_CREDENTIAL_NAME)
    if stored is not None and stored.strip():
        return stored.strip()

    # `load_env_file` has already applied `.env` to the environment by the time
    # any request runs, so reading the environment covers both a real
    # environment variable and a `.env` entry.
    from_env = os.environ.get(OPENAI_CREDENTIAL_NAME, "").strip()
    return from_env or None


__all__ = [
    "OPENAI_CREDENTIAL_NAME",
    "CredentialStore",
    "UnavailableCredentialStore",
    "default_credential_store",
    "resolve_openai_api_key",
]
