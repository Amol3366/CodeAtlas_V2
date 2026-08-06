# Frontend OpenAI Credential Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user enter the OpenAI API key in the web Settings page, stored in the Windows Credential Manager instead of a plaintext `.env` file.

**Architecture:** A narrow `CredentialStore` interface with a Windows (`ctypes`/`advapi32`) implementation and an unavailable-elsewhere fallback. One `resolve_openai_api_key()` choke point replaces four direct `os.environ` reads, with precedence credential-store → `.env`. Three additive REST endpoints expose write and status, never the value. No SQLite storage, so no migration.

**Tech Stack:** Python 3.12, `ctypes` (stdlib — no new dependency), FastAPI, Pydantic, pytest, React 18 + TypeScript, TanStack Query, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-06-frontend-credential-entry-design.md`

## Global Constraints

- **No new dependency.** `ctypes` is stdlib. `documentation/rules.md` forbids adding one without asking.
- **The resolved key is NEVER written into `os.environ`.** Child processes inherit the parent environment and CodeAtlas shells out to Git. This is asserted by a test, not just a comment.
- **No response body ever contains the key or any part of it** — no masking, no last-4. `AGENTS.md` §12.5.
- **No migration.** `SCHEMA_VERSION` stays **14**. `contract_version` stays **`1.1`**.
- Machine-wide scope; precedence is credential store → `.env`.
- Windows-only tests skip (never fail) on other platforms, following the existing convention in `tests/unit/test_embedding_providers.py`.
- Error responses carry a stable `code` and never provider text (`_failure_code` precedent).
- Existing style: `from __future__ import annotations`, full type hints, strict MyPy, Ruff.
- Run `uv run ruff check src tests scripts apps` and `uv run mypy --no-incremental src tests scripts apps` before every commit.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/codeatlas/settings/credentials.py` (new) | `CredentialStore` protocol, both implementations, platform selection, `resolve_openai_api_key()` |
| `src/codeatlas/application/credentials.py` (new) | `CredentialService` — the application boundary adapters call |
| `src/codeatlas/domain/errors.py` (modify) | Two new error codes and their exception classes |
| `src/codeatlas/application/container.py` (modify) | Wire `CredentialService` into `ApplicationServices` |
| `src/codeatlas/api/routers/settings.py` (modify) | Three additive routes |
| `src/codeatlas/api/errors.py` (modify) | HTTP status for the two new codes |
| `src/codeatlas/semantic/providers.py` (modify) | Two read sites → the choke point |
| `src/codeatlas/generation/openai_provider.py` (modify) | One read site → the choke point |
| `src/codeatlas/generation/factory.py` (modify) | One read site → the choke point |
| `apps/web/src/lib/api.ts` (modify) | Add the `put` verb |
| `apps/web/src/lib/queries.ts` (modify) | Credential status query + set/clear mutations |
| `apps/web/src/features/settings/SemanticSettings.tsx` (modify) | Password field, four states, Save/Clear |

---

### Task 1: Error codes and the `CredentialStore` interface

**Files:**
- Create: `src/codeatlas/settings/credentials.py`
- Modify: `src/codeatlas/domain/errors.py`
- Test: `tests/unit/test_credential_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CredentialStore` (protocol with `is_available() -> bool`, `get(name: str) -> str | None`, `set(name: str, value: str) -> None`, `clear(name: str) -> None`); `UnavailableCredentialStore`; `OPENAI_CREDENTIAL_NAME: Final[str] = "OPENAI_API_KEY"`; `CredentialStoreUnavailableError`; `CredentialWriteFailedError`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_credential_store.py`:

```python
"""The credential store boundary.

The store is the only place a secret is written, so its failure modes are
tested before its happy path: an unavailable store must be a clear refusal,
never a silent no-op that reports success while storing nothing.
"""

from __future__ import annotations

import pytest

from codeatlas.domain.errors import CredentialStoreUnavailableError
from codeatlas.settings.credentials import (
    OPENAI_CREDENTIAL_NAME,
    UnavailableCredentialStore,
)


def test_the_unavailable_store_reports_itself_unavailable() -> None:
    assert UnavailableCredentialStore().is_available() is False


def test_the_unavailable_store_holds_nothing() -> None:
    assert UnavailableCredentialStore().get(OPENAI_CREDENTIAL_NAME) is None


def test_the_unavailable_store_refuses_a_write_rather_than_dropping_it() -> None:
    """A silent no-op would tell the user their key was saved when it was not."""
    with pytest.raises(CredentialStoreUnavailableError):
        UnavailableCredentialStore().set(OPENAI_CREDENTIAL_NAME, "sk-test")


def test_clearing_an_unavailable_store_is_not_an_error() -> None:
    """Clearing is idempotent: "there is nothing stored" is the desired state."""
    UnavailableCredentialStore().clear(OPENAI_CREDENTIAL_NAME)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_credential_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codeatlas.settings.credentials'`

- [ ] **Step 3: Add the error codes**

In `src/codeatlas/domain/errors.py`, add to the `ErrorCode` enum immediately after `PROVIDER_BUDGET_EXCEEDED`:

```python
    CREDENTIAL_STORE_UNAVAILABLE = "CREDENTIAL_STORE_UNAVAILABLE"
    CREDENTIAL_WRITE_FAILED = "CREDENTIAL_WRITE_FAILED"
```

Then add the exception classes at the end of the file, next to the other provider errors:

```python
class CredentialStoreUnavailableError(CodeAtlasError):
    """No OS credential store on this platform.

    Not an internal error: on a non-Windows machine this is the expected
    state, and `.env` remains a supported way to supply the key.
    """

    code = ErrorCode.CREDENTIAL_STORE_UNAVAILABLE


class CredentialWriteFailedError(CodeAtlasError):
    """The OS credential store rejected the write.

    The underlying Windows error code goes in `details`, never the value that
    was being written.
    """

    code = ErrorCode.CREDENTIAL_WRITE_FAILED
```

- [ ] **Step 4: Create the interface module**

Create `src/codeatlas/settings/credentials.py`:

```python
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

# Namespaced so the entry is identifiable in the Windows Credential Manager UI
# and cannot collide with another application's generic credential.
_TARGET_PREFIX: Final[str] = "CodeAtlas/"


class CredentialStore(Protocol):
    """A place to keep one named secret.

    Narrow on purpose (`AGENTS.md` Section 4.5): the platform API behind it is
    substitutable, and the application layer never learns which one it got.
    """

    def is_available(self) -> bool:
        """Whether this store can hold anything on this machine."""

    def get(self, name: str) -> str | None:
        """The stored value, or `None` when absent or unreadable."""

    def set(self, name: str, value: str) -> None:
        """Store `value`, replacing any existing entry."""

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


def _target_name(name: str) -> str:
    return f"{_TARGET_PREFIX}{name}"


def default_credential_store() -> CredentialStore:
    """The store for this platform.

    Selected by platform rather than by trying and catching, so a settings page
    can report availability without attempting a write.
    """
    if sys.platform == "win32":
        from codeatlas.settings.windows_credentials import WindowsCredentialStore

        return WindowsCredentialStore()
    return UnavailableCredentialStore()


__all__ = [
    "OPENAI_CREDENTIAL_NAME",
    "CredentialStore",
    "UnavailableCredentialStore",
    "default_credential_store",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_credential_store.py -v`
Expected: PASS — 4 tests. `default_credential_store()` is not exercised yet; its Windows import target arrives in Task 2.

- [ ] **Step 6: Lint and type check**

Run: `uv run ruff check src tests && uv run mypy --no-incremental src tests`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/settings/credentials.py src/codeatlas/domain/errors.py tests/unit/test_credential_store.py
git commit -m "feat: add the credential store boundary and its two error codes"
```

---

### Task 2: `WindowsCredentialStore`

**Files:**
- Create: `src/codeatlas/settings/windows_credentials.py`
- Test: `tests/unit/test_windows_credential_store.py`

**Interfaces:**
- Consumes: `CredentialStore`, `_target_name`, `CredentialWriteFailedError` from Task 1.
- Produces: `WindowsCredentialStore` satisfying `CredentialStore`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_windows_credential_store.py`:

```python
"""The real Windows Credential Manager, exercised against the real API.

Not mocked. A mocked ctypes call proves only that the mock was called: the
struct layout, the string encoding, and the persistence flag are exactly what
would be wrong, and only the real API can reject them.

The entry is written under a test-only name and removed in a finally block, so
a failing assertion cannot leave a credential behind on the developer's
machine.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the Windows Credential Manager is Windows-only"
)

TEST_NAME = "CODEATLAS_TEST_CREDENTIAL"


def _store():
    from codeatlas.settings.windows_credentials import WindowsCredentialStore

    return WindowsCredentialStore()


def test_the_windows_store_is_available() -> None:
    assert _store().is_available() is True


def test_a_written_credential_reads_back_unchanged() -> None:
    store = _store()
    try:
        store.set(TEST_NAME, "sk-round-trip-value")
        assert store.get(TEST_NAME) == "sk-round-trip-value"
    finally:
        store.clear(TEST_NAME)


def test_a_non_ascii_credential_survives_the_round_trip() -> None:
    """The blob is UTF-16LE. A key is ASCII today, but a truncating encoding
    would corrupt silently rather than raise, so it is pinned here."""
    store = _store()
    try:
        store.set(TEST_NAME, "sk-éü-中文")
        assert store.get(TEST_NAME) == "sk-éü-中文"
    finally:
        store.clear(TEST_NAME)


def test_writing_twice_replaces_rather_than_duplicates() -> None:
    store = _store()
    try:
        store.set(TEST_NAME, "first")
        store.set(TEST_NAME, "second")
        assert store.get(TEST_NAME) == "second"
    finally:
        store.clear(TEST_NAME)


def test_a_cleared_credential_is_gone() -> None:
    store = _store()
    store.set(TEST_NAME, "to-be-removed")
    store.clear(TEST_NAME)
    assert store.get(TEST_NAME) is None


def test_clearing_an_absent_credential_is_not_an_error() -> None:
    _store().clear("CODEATLAS_TEST_NEVER_WRITTEN")


def test_reading_an_absent_credential_returns_none() -> None:
    assert _store().get("CODEATLAS_TEST_NEVER_WRITTEN") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_windows_credential_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codeatlas.settings.windows_credentials'`

- [ ] **Step 3: Write the implementation**

Create `src/codeatlas/settings/windows_credentials.py`:

```python
"""The Windows Credential Manager, reached through `ctypes`.

Imported only on Windows, by `default_credential_store()`. Kept in its own
module so the platform-specific `ctypes` structures never load on a platform
that cannot use them, and so the boundary in `credentials.py` stays readable.

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

_TARGET_PREFIX: Final[str] = "CodeAtlas/"


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
    return f"{_TARGET_PREFIX}{name}"


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
            # Absent is the common case and is not an error. Any other failure
            # is also reported as "no key": a settings page that cannot read
            # the store should behave as though nothing is configured rather
            # than fail the whole request.
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
        credential.CredentialBlob = ctypes.cast(
            buffer, ctypes.POINTER(ctypes.c_byte)
        )
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_windows_credential_store.py -v`
Expected: PASS — 7 tests on Windows.

- [ ] **Step 5: Verify the entry is really gone**

Run: `cmdkey /list:CodeAtlas/CODEATLAS_TEST_CREDENTIAL`
Expected: `* NONE *` — the tests cleaned up after themselves.

- [ ] **Step 6: Lint and type check**

Run: `uv run ruff check src tests && uv run mypy --no-incremental src tests`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add src/codeatlas/settings/windows_credentials.py tests/unit/test_windows_credential_store.py
git commit -m "feat: store a credential in the Windows Credential Manager"
```

---

### Task 3: `resolve_openai_api_key()` and the four read sites

**Files:**
- Modify: `src/codeatlas/settings/credentials.py`
- Modify: `src/codeatlas/semantic/providers.py:259` and `:399`
- Modify: `src/codeatlas/generation/openai_provider.py:59`
- Modify: `src/codeatlas/generation/factory.py:90`
- Test: `tests/unit/test_credential_resolution.py`

**Interfaces:**
- Consumes: `CredentialStore`, `OPENAI_CREDENTIAL_NAME`, `default_credential_store` from Task 1.
- Produces: `resolve_openai_api_key(store: CredentialStore | None = None) -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_credential_resolution.py`:

```python
"""The precedence ladder, and the rule that the key stays out of the environment.

Mirrors ADR-0014's policy -> .env -> default ordering, so the codebase has one
precedence rule rather than two that disagree.
"""

from __future__ import annotations

import os

import pytest

from codeatlas.settings.credentials import (
    OPENAI_CREDENTIAL_NAME,
    UnavailableCredentialStore,
    resolve_openai_api_key,
)


class FakeStore:
    """A store holding exactly what a test puts in it."""

    def __init__(self, value: str | None) -> None:
        self._value = value

    def is_available(self) -> bool:
        return True

    def get(self, name: str) -> str | None:
        return self._value

    def set(self, name: str, value: str) -> None:
        self._value = value

    def clear(self, name: str) -> None:
        self._value = None


def test_the_stored_key_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    assert resolve_openai_api_key(FakeStore("sk-from-store")) == "sk-from-store"


def test_env_is_used_when_the_store_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    assert resolve_openai_api_key(FakeStore(None)) == "sk-from-env"


def test_env_is_used_when_the_store_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    assert resolve_openai_api_key(UnavailableCredentialStore()) == "sk-from-env"


def test_nothing_anywhere_resolves_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    assert resolve_openai_api_key(FakeStore(None)) is None


def test_a_blank_stored_value_falls_through_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty entry is indistinguishable from no entry to a user, so it must
    not shadow a working .env value."""
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    assert resolve_openai_api_key(FakeStore("   ")) == "sk-from-env"


def test_resolution_never_publishes_the_key_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subprocess-inheritance constraint, as a test rather than a comment.

    CodeAtlas shells out to Git, and a child process inherits its parent's
    environment. A key placed in os.environ is handed to every Git invocation
    for the life of the server.
    """
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)

    assert resolve_openai_api_key(FakeStore("sk-must-not-leak")) == "sk-must-not-leak"

    assert OPENAI_CREDENTIAL_NAME not in os.environ
    assert "sk-must-not-leak" not in repr(dict(os.environ))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_credential_resolution.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_openai_api_key'`

- [ ] **Step 3: Add the resolver**

Append to `src/codeatlas/settings/credentials.py`, before `__all__`:

```python
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
```

Add `"resolve_openai_api_key"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_credential_resolution.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 5: Rewire read site 1 — embedding provider construction**

In `src/codeatlas/semantic/providers.py` around line 259, replace:

```python
        api_key = os.environ.get(OPENAI_API_KEY_VARIABLE)
```

with:

```python
        from codeatlas.settings.credentials import resolve_openai_api_key

        api_key = resolve_openai_api_key()
```

- [ ] **Step 6: Rewire read site 2 — embedding availability**

In the same file around line 399, inside `describe_available_providers()`, replace:

```python
        EmbeddingProviderKind.OPENAI: (
            _module_is_importable("openai")
            and bool(os.environ.get(OPENAI_API_KEY_VARIABLE))
        ),
```

with:

```python
        EmbeddingProviderKind.OPENAI: (
            _module_is_importable("openai") and bool(resolve_openai_api_key())
        ),
```

Add at the top of that function, beside the existing `import os`:

```python
    from codeatlas.settings.credentials import resolve_openai_api_key
```

- [ ] **Step 7: Rewire read site 3 — answer request authorization**

In `src/codeatlas/generation/openai_provider.py` around line 59, replace:

```python
                "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"
```

with:

```python
                "Authorization": f"Bearer {resolve_openai_api_key() or ''}"
```

and add to that module's imports:

```python
from codeatlas.settings.credentials import resolve_openai_api_key
```

- [ ] **Step 8: Rewire read site 4 — answer availability**

In `src/codeatlas/generation/factory.py` around line 90, replace:

```python
            os.environ.get(OPENAI_API_KEY_VARIABLE, "").strip()
```

with:

```python
            (resolve_openai_api_key() or "").strip()
```

and add:

```python
from codeatlas.settings.credentials import resolve_openai_api_key
```

- [ ] **Step 9: Verify no direct read remains**

Run: `git grep -n "environ.get(.OPENAI_API_KEY\|environ.get(OPENAI_API_KEY_VARIABLE" -- src/`
Expected: only `src/codeatlas/settings/credentials.py` — the choke point itself.

- [ ] **Step 10: Run the full Python suite**

Run: `uv run pytest tests/unit tests/contract tests/integration -q`
Expected: PASS. If `test_no_credential_appears_in_any_response` fails, a read site was rewired incorrectly — do not weaken the test.

- [ ] **Step 11: Lint and type check**

Run: `uv run ruff check src tests && uv run mypy --no-incremental src tests`
Expected: both clean. Remove any `os` import left unused.

- [ ] **Step 12: Commit**

```bash
git add src/codeatlas/settings/credentials.py src/codeatlas/semantic/providers.py src/codeatlas/generation/openai_provider.py src/codeatlas/generation/factory.py tests/unit/test_credential_resolution.py
git commit -m "refactor: resolve the OpenAI key through one choke point"
```

---

### Task 4: `CredentialService` and container wiring

**Files:**
- Create: `src/codeatlas/application/credentials.py`
- Modify: `src/codeatlas/application/container.py`
- Test: `tests/integration/test_credential_service.py`

**Interfaces:**
- Consumes: `CredentialStore`, `OPENAI_CREDENTIAL_NAME`, `resolve_openai_api_key`, `default_credential_store`.
- Produces: `CredentialStatus` (frozen dataclass: `configured: bool`, `source: str | None`, `store_available: bool`); `CredentialService` with `status() -> CredentialStatus`, `set_openai_key(value: str) -> CredentialStatus`, `clear_openai_key() -> CredentialStatus`. `ApplicationServices.credentials`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_credential_service.py`:

```python
"""The application boundary adapters call for credential state."""

from __future__ import annotations

import pytest

from codeatlas.application.credentials import CredentialService
from codeatlas.domain.errors import InvalidRequestError
from codeatlas.settings.credentials import OPENAI_CREDENTIAL_NAME


class FakeStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def is_available(self) -> bool:
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def clear(self, name: str) -> None:
        self.values.pop(name, None)


def test_nothing_configured_is_reported_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    status = CredentialService(FakeStore()).status()

    assert status.configured is False
    assert status.source is None
    assert status.store_available is True


def test_a_saved_key_reports_the_store_as_its_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    service = CredentialService(FakeStore())

    status = service.set_openai_key("sk-saved")

    assert status.configured is True
    assert status.source == "credential_store"


def test_an_env_key_is_reported_as_coming_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user who saved nothing but sees "configured" needs to know why."""
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    status = CredentialService(FakeStore()).status()

    assert status.configured is True
    assert status.source == "env"


def test_clearing_removes_the_stored_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    service = CredentialService(FakeStore())
    service.set_openai_key("sk-saved")

    status = service.clear_openai_key()

    assert status.configured is False
    assert status.source is None


def test_clearing_does_not_touch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clearing must not edit a file the user owns, so a .env key survives."""
    monkeypatch.setenv(OPENAI_CREDENTIAL_NAME, "sk-from-env")
    service = CredentialService(FakeStore())
    service.set_openai_key("sk-saved")

    status = service.clear_openai_key()

    assert status.configured is True
    assert status.source == "env"


def test_an_empty_key_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        CredentialService(FakeStore()).set_openai_key("   ")


def test_an_overlong_key_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        CredentialService(FakeStore()).set_openai_key("s" * 501)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_credential_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codeatlas.application.credentials'`

- [ ] **Step 3: Write the service**

Create `src/codeatlas/application/credentials.py`:

```python
"""Reading and writing the provider credential, as an application service.

Adapters call this rather than a store directly (Section 4.5). It is thin by
design: the interesting decisions live in `settings/credentials.py`, and this
layer adds validation and the status shape the delivery surfaces need.

Nothing here ever returns the credential itself. `CredentialStatus` is the
whole vocabulary: whether one is configured, where it came from, and whether
this machine can store one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from codeatlas.domain.errors import InvalidRequestError
from codeatlas.settings.credentials import (
    OPENAI_CREDENTIAL_NAME,
    CredentialStore,
    default_credential_store,
    resolve_openai_api_key,
)

# Generous rather than tight. Key formats have changed more than once, and a
# bound that rejects a valid future key is a support report that reads as "the
# product is broken" while looking correct in tests.
MAX_CREDENTIAL_LENGTH: Final[int] = 500

SOURCE_STORE: Final[str] = "credential_store"
SOURCE_ENV: Final[str] = "env"


@dataclass(frozen=True)
class CredentialStatus:
    """What may be said about a credential without revealing it."""

    configured: bool
    # Which source is actually in effect: a user who saved a key and still sees
    # `env` is being shadowed, and needs to know that rather than guess.
    source: str | None
    store_available: bool


class CredentialService:
    """The provider credential, as the delivery layer sees it."""

    def __init__(self, store: CredentialStore | None = None) -> None:
        self._store = store if store is not None else default_credential_store()

    def status(self) -> CredentialStatus:
        stored = self._store.get(OPENAI_CREDENTIAL_NAME)
        if stored is not None and stored.strip():
            source: str | None = SOURCE_STORE
        elif resolve_openai_api_key(self._store) is not None:
            source = SOURCE_ENV
        else:
            source = None
        return CredentialStatus(
            configured=source is not None,
            source=source,
            store_available=self._store.is_available(),
        )

    def set_openai_key(self, value: str) -> CredentialStatus:
        cleaned = value.strip()
        if not cleaned:
            raise InvalidRequestError(
                "An API key is required.", details={"field": "api_key"}
            )
        if len(cleaned) > MAX_CREDENTIAL_LENGTH:
            raise InvalidRequestError(
                f"An API key is limited to {MAX_CREDENTIAL_LENGTH} characters.",
                details={"field": "api_key"},
            )
        self._store.set(OPENAI_CREDENTIAL_NAME, cleaned)
        return self.status()

    def clear_openai_key(self) -> CredentialStatus:
        """Remove the stored key.

        `.env` is deliberately untouched: it is a file the user owns, and an
        application that edits it would be making a change the user did not ask
        for in a place they did not look.
        """
        self._store.clear(OPENAI_CREDENTIAL_NAME)
        return self.status()


__all__ = [
    "MAX_CREDENTIAL_LENGTH",
    "CredentialService",
    "CredentialStatus",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_credential_service.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 5: Wire it into the container**

In `src/codeatlas/application/container.py`, add the import beside the other application imports:

```python
from codeatlas.application.credentials import CredentialService
```

Add the field to `ApplicationServices`, immediately after `settings`:

```python
    # Holds no connection: the credential lives in an OS store, not in SQLite,
    # so a backup and a support bundle cannot carry it.
    credentials: CredentialService
```

Construct it beside `settings = SettingsService(connection)`:

```python
    credentials = CredentialService()
```

and pass it in the `ApplicationServices(...)` call beside `settings=settings`:

```python
        credentials=credentials,
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/unit tests/contract tests/integration -q`
Expected: PASS.

- [ ] **Step 7: Lint and type check**

Run: `uv run ruff check src tests && uv run mypy --no-incremental src tests`
Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add src/codeatlas/application/credentials.py src/codeatlas/application/container.py tests/integration/test_credential_service.py
git commit -m "feat: add the credential application service"
```

---

### Task 5: REST endpoints

**Files:**
- Modify: `src/codeatlas/api/routers/settings.py`
- Modify: `src/codeatlas/api/errors.py`
- Modify: `apps/web/openapi.json`, `apps/web/src/lib/api-types.gen.ts` (regenerated, never hand-edited)
- Test: `tests/contract/test_credentials_api.py`

**Interfaces:**
- Consumes: `CredentialService`, `CredentialStatus` from Task 4.
- Produces: `GET /v1/credentials`, `PUT /v1/credentials/openai`, `DELETE /v1/credentials/openai`.

- [ ] **Step 1: Write the failing test**

Create `tests/contract/test_credentials_api.py`:

```python
"""The credential endpoints (`AGENTS.md` Section 12.5).

Every test here is ultimately the same assertion in a different place: the
value goes in and never comes back out.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.settings.credentials import OPENAI_CREDENTIAL_NAME
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SECRET = "sk-" + "contract" * 5


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # No ambient key: these tests are about what the endpoints do, not about
    # what happens to be configured on the machine running them.
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    database_path = tmp_path / "db.sqlite"
    with connect(database_path) as connection:
        apply_migrations(connection)
    with TestClient(create_app(database_path, watch=False)) as test_client:
        yield test_client


def test_status_reports_nothing_configured(client: TestClient) -> None:
    response = client.get("/v1/credentials")

    assert response.status_code == 200, response.text
    body = response.json()["openai"]
    assert body["configured"] is False
    assert body["source"] is None
    assert "store_available" in body


def test_status_never_carries_a_value_field(client: TestClient) -> None:
    """Section 12.5 has no exception for part of a secret, so there is no
    field a value could occupy - not even a masked one."""
    body = client.get("/v1/credentials").json()["openai"]

    assert set(body) == {"configured", "source", "store_available"}


def test_an_empty_key_is_refused(client: TestClient) -> None:
    response = client.put("/v1/credentials/openai", json={"api_key": ""})

    assert response.status_code == 422


def test_an_overlong_key_is_refused(client: TestClient) -> None:
    response = client.put("/v1/credentials/openai", json={"api_key": "s" * 501})

    assert response.status_code == 422


def test_an_unknown_field_is_refused(client: TestClient) -> None:
    response = client.put(
        "/v1/credentials/openai", json={"api_key": SECRET, "extra": 1}
    )

    assert response.status_code == 422


def test_deleting_an_absent_credential_succeeds(client: TestClient) -> None:
    """Idempotent: the caller wants "no key stored", and that already holds."""
    response = client.delete("/v1/credentials/openai")

    assert response.status_code == 200, response.text
    assert response.json()["openai"]["configured"] is False


def test_no_endpoint_echoes_the_key_back(client: TestClient) -> None:
    """The single assertion this whole surface exists to keep.

    Skipped where no credential store exists, because there is nowhere to
    write the key and the PUT correctly refuses.
    """
    written = client.put("/v1/credentials/openai", json={"api_key": SECRET})
    if written.status_code != 200:
        pytest.skip("no credential store on this platform")

    try:
        bodies = [
            written.text,
            client.get("/v1/credentials").text,
            client.get("/v1/models").text,
        ]
        assert all(SECRET not in body for body in bodies)
    finally:
        client.delete("/v1/credentials/openai")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/contract/test_credentials_api.py -v`
Expected: FAIL — 404 on every route.

- [ ] **Step 3: Map the new codes to HTTP status**

In `src/codeatlas/api/errors.py`, add to `_STATUS_BY_CODE` beside the other provider codes:

```python
    # Conflict, not a server error: the request is well formed and the service
    # is running; this machine simply has nowhere to put a credential.
    ErrorCode.CREDENTIAL_STORE_UNAVAILABLE: status.HTTP_409_CONFLICT,
    ErrorCode.CREDENTIAL_WRITE_FAILED: status.HTTP_409_CONFLICT,
```

- [ ] **Step 4: Add the routes**

In `src/codeatlas/api/routers/settings.py`, add the models beside the other `StrictModel` definitions:

```python
class CredentialStatusResponse(StrictModel):
    """Status only. There is deliberately no field a value could occupy."""

    configured: bool
    source: Literal["credential_store", "env"] | None
    store_available: bool


class CredentialsResponse(StrictModel):
    openai: CredentialStatusResponse


class SetCredentialBody(StrictModel):
    # 500 rather than the 200 used for model ids: a key is not a model id and
    # has grown longer across format changes.
    api_key: str = Field(min_length=1, max_length=500)
```

Add the routes at the end of the module:

```python
def _credentials(services: Services) -> CredentialsResponse:
    status = services.credentials.status()
    return CredentialsResponse(
        openai=CredentialStatusResponse(
            configured=status.configured,
            source=status.source,  # type: ignore[arg-type]
            store_available=status.store_available,
        )
    )


@router.get("/v1/credentials")
def get_credentials(services: Services) -> CredentialsResponse:
    """Whether a provider credential is configured, and from where.

    Never what it is. `source` exists so a user whose saved key is being
    shadowed by `.env` can see that rather than guess.
    """
    return _credentials(services)


@router.put("/v1/credentials/openai")
def set_openai_credential(
    services: Services, body: SetCredentialBody
) -> CredentialsResponse:
    """Store the OpenAI API key. Write-only: the response is a status.

    Separate from `PATCH /v1/settings` on purpose. A credential is not a
    policy, and folding it into the settings save would report a failed
    credential write as a failed settings save.
    """
    services.credentials.set_openai_key(body.api_key)
    return _credentials(services)


@router.delete("/v1/credentials/openai")
def clear_openai_credential(services: Services) -> CredentialsResponse:
    """Remove the stored key. `.env` is not touched."""
    services.credentials.clear_openai_key()
    return _credentials(services)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/contract/test_credentials_api.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 6: Regenerate the API types**

Run: `powershell -ExecutionPolicy Bypass -File scripts/generate_web_types.ps1`
Expected: "Web API types regenerated." Never hand-edit `api-types.gen.ts`.

- [ ] **Step 7: Confirm no value field reached the schema**

Run: `git grep -n "api_key" -- apps/web/openapi.json`
Expected: only inside `SetCredentialBody` — the request. No response schema names it.

- [ ] **Step 8: Lint and type check**

Run: `uv run ruff check src tests && uv run mypy --no-incremental src tests`
Expected: both clean.

- [ ] **Step 9: Commit**

```bash
git add src/codeatlas/api/routers/settings.py src/codeatlas/api/errors.py tests/contract/test_credentials_api.py apps/web/openapi.json apps/web/src/lib/api-types.gen.ts
git commit -m "feat: add write-only credential endpoints"
```

---

### Task 6: Security tests

**Files:**
- Create: `tests/security/test_credential_confinement.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5. Produces no new interface.

- [ ] **Step 1: Write the failing test**

Create `tests/security/test_credential_confinement.py`:

```python
"""Where the credential must never appear.

The controls in this file are the reason the feature is allowed to exist. They
are written as their own suite rather than folded into the contract tests
because they assert absence, and absence is what silently stops being true.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.api.app import create_app
from codeatlas.application.credentials import CredentialService
from codeatlas.settings.credentials import OPENAI_CREDENTIAL_NAME
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

SECRET = "sk-" + "confine" * 6


class FakeStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def is_available(self) -> bool:
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def clear(self, name: str) -> None:
        self.values.pop(name, None)


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    path = tmp_path / "db.sqlite"
    with connect(path) as connection:
        apply_migrations(connection)
    return path


def test_a_stored_key_never_enters_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Git is invoked as a subprocess and inherits this environment."""
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    store = FakeStore()
    service = CredentialService(store)

    service.set_openai_key(SECRET)
    assert service.status().configured is True

    assert OPENAI_CREDENTIAL_NAME not in os.environ
    assert SECRET not in "".join(os.environ.values())


def test_a_stored_key_is_absent_from_the_database(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database is copied by backup and attached to bug reports."""
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    CredentialService(FakeStore()).set_openai_key(SECRET)

    assert SECRET.encode() not in database.read_bytes()


def test_a_rejected_write_does_not_log_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    service = CredentialService(FakeStore())

    with caplog.at_level(logging.DEBUG):
        service.set_openai_key(SECRET)
        with pytest.raises(Exception):
            service.set_openai_key("s" * 501)

    assert SECRET not in caplog.text


def test_diagnostics_never_carry_the_key(
    database: Path, monkeypatch: pytest.MonkeyPatch, sample_repo: Path
) -> None:
    monkeypatch.delenv(OPENAI_CREDENTIAL_NAME, raising=False)
    with TestClient(create_app(database, watch=False)) as client:
        written = client.put("/v1/credentials/openai", json={"api_key": SECRET})
        if written.status_code != 200:
            pytest.skip("no credential store on this platform")
        try:
            repository_id = client.post(
                "/v1/repositories", json={"path": str(sample_repo)}
            ).json()["repository_id"]

            bodies = [
                client.get(f"/v1/repositories/{repository_id}/diagnostics").text,
                client.get(f"/v1/repositories/{repository_id}/status").text,
                client.get("/v1/credentials").text,
                client.get("/v1/models").text,
            ]
            assert all(SECRET not in body for body in bodies)
        finally:
            client.delete("/v1/credentials/openai")
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `uv run pytest tests/security/test_credential_confinement.py -v`
Expected: PASS if Tasks 1-5 were implemented correctly. **A failure here is a real defect, not a test to adjust.** If `test_a_stored_key_never_enters_the_process_environment` fails, something writes the resolved key into `os.environ` — find and remove it.

- [ ] **Step 3: Lint and type check**

Run: `uv run ruff check src tests && uv run mypy --no-incremental src tests`
Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add tests/security/test_credential_confinement.py
git commit -m "test: assert the credential stays out of env, database, logs, and diagnostics"
```

---

### Task 7: Frontend

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`
- Modify: `apps/web/src/features/settings/SemanticSettings.tsx`
- Test: `apps/web/src/features/settings/SemanticSettings.test.tsx`

**Interfaces:**
- Consumes: the three endpoints from Task 5.
- Produces: `CredentialStatus` and `Credentials` TS interfaces; `useCredentials()`, `useSetOpenAiKey()`, `useClearOpenAiKey()`.

- [ ] **Step 1: Add the credential route to the shared stub defaults**

`SemanticSettings` will call `/v1/credentials` on every render, so **every existing test in the file breaks with a `NOT_STUBBED` 500 unless the default stub answers it.** Do this before writing new tests, or the failures you see next will be the old tests rather than the new ones.

In `apps/web/src/features/settings/SemanticSettings.test.tsx`, add to the `stubFetch({...})` map inside `stubBackend`, before `...overrides`:

```tsx
    "/v1/credentials": {
      body: {
        openai: { configured: false, source: null, store_available: true },
      },
    },
```

`stubFetch` matches `` `${method} ${url}` `` first and falls back to `url` (`harness.tsx:69`), so this verb-less key answers the `GET` while the per-test overrides below can still target `"PUT /v1/credentials/openai"` specifically.

- [ ] **Step 2: Confirm the existing tests still pass**

Run: `pnpm --dir apps/web test -- SemanticSettings`
Expected: PASS — unchanged count. This proves the default stub is wired before any new behavior is added.

- [ ] **Step 3: Write the failing test**

Add to `apps/web/src/features/settings/SemanticSettings.test.tsx`:

```tsx
  it("never populates the key field from the server", async () => {
    stubBackend({
      "GET /v1/credentials": {
        body: {
          openai: {
            configured: true,
            source: "credential_store",
            store_available: true,
          },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    const field = await screen.findByLabelText(/openai api key/i);
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveValue("");
  });

  it("says where a configured key came from", async () => {
    stubBackend({
      "GET /v1/credentials": {
        body: {
          openai: { configured: true, source: "env", store_available: true },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await screen.findByText(/configured from \.env/i);
  });

  it("sends the typed key and clears the field afterwards", async () => {
    const fetchMock = stubBackend({
      "GET /v1/credentials": {
        body: {
          openai: { configured: false, source: null, store_available: true },
        },
      },
      "PUT /v1/credentials/openai": {
        body: {
          openai: {
            configured: true,
            source: "credential_store",
            store_available: true,
          },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await userEvent.type(
      await screen.findByLabelText(/openai api key/i),
      "sk-typed-by-user",
    );
    await userEvent.click(screen.getByRole("button", { name: /save key/i }));

    const put = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes("/v1/credentials/openai") &&
        (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(put).toBeDefined();
    const body = JSON.parse(String((put?.[1] as RequestInit).body)) as Record<
      string,
      unknown
    >;
    expect(body["api_key"]).toBe("sk-typed-by-user");

    // The field is emptied once the key is stored: leaving it populated
    // invites a second save and keeps the secret in the DOM.
    expect(screen.getByLabelText(/openai api key/i)).toHaveValue("");
  });

  it("explains itself when the machine has no credential store", async () => {
    stubBackend({
      "GET /v1/credentials": {
        body: {
          openai: { configured: false, source: null, store_available: false },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await screen.findByText(/credential store is unavailable/i);
  });
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pnpm --dir apps/web test -- SemanticSettings`
Expected: FAIL — no element labelled "OpenAI API key".

- [ ] **Step 5: Add the `put` verb**

In `apps/web/src/lib/api.ts`, add to the `api` object beside `patch`:

```ts
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
```

- [ ] **Step 6: Add the query hooks**

In `apps/web/src/lib/queries.ts`, add:

```ts
/** Status only. The API has no field carrying the key, and neither has this. */
export interface CredentialStatus {
  readonly configured: boolean;
  readonly source: "credential_store" | "env" | null;
  readonly store_available: boolean;
}

export interface Credentials {
  readonly openai: CredentialStatus;
}

export function useCredentials() {
  return useQuery({
    queryKey: ["credentials"] as const,
    queryFn: () => api.get<Credentials>("/v1/credentials"),
    refetchOnMount: "always",
  });
}

export function useSetOpenAiKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (apiKey: string) =>
      api.put<Credentials>("/v1/credentials/openai", { api_key: apiKey }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["credentials"] });
      // Availability depends on the key, so the model list is stale the
      // moment one is stored or removed.
      void client.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

export function useClearOpenAiKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete<Credentials>("/v1/credentials/openai"),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["credentials"] });
      void client.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
```

- [ ] **Step 7: Add the field to Settings**

In `SemanticSettings.tsx`, add to the imports:

```tsx
import {
  useClearOpenAiKey,
  useCredentials,
  useSetOpenAiKey,
} from "../../lib/queries";
```

Add beside the other hooks in the component:

```tsx
  const credentials = useCredentials();
  const setKey = useSetOpenAiKey();
  const clearKey = useClearOpenAiKey();
  const [apiKey, setApiKey] = useState<string>("");
```

Add this section inside the `aside`, after the embedding-model section:

```tsx
  {/*
    Write-only. The field is never populated from a response, because the
    server has no field that carries the key and this form must not invent
    one. It is emptied after a successful save so the secret does not sit in
    the DOM waiting to be re-submitted.
  */}
  <section className="rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-4)] shadow-sm">
    <label htmlFor="openai-api-key" className="block text-sm font-medium">
      OpenAI API key
    </label>
    <p className="mt-[var(--space-2)] text-xs leading-5 text-text-muted">
      {credentials.data?.openai.store_available === false
        ? "The credential store is unavailable on this platform. Set OPENAI_API_KEY in .env instead."
        : credentials.data?.openai.source === "credential_store"
          ? "Configured, stored in the Windows Credential Manager."
          : credentials.data?.openai.source === "env"
            ? "Configured from .env. A key saved here would take precedence."
            : "Not configured. Stored in the Windows Credential Manager, never in the database."}
    </p>
    <input
      id="openai-api-key"
      type="password"
      autoComplete="off"
      value={apiKey}
      onChange={(event) => setApiKey(event.target.value)}
      disabled={credentials.data?.openai.store_available === false}
      className="mt-[var(--space-2)] w-full rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-3)] py-[var(--space-2)] text-sm"
    />
    <div className="mt-[var(--space-3)] flex gap-[var(--space-2)]">
      <button
        type="button"
        onClick={() => {
          setKey.mutate(apiKey.trim(), { onSuccess: () => setApiKey("") });
        }}
        disabled={setKey.isPending || apiKey.trim() === ""}
        className="flex-1 rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium disabled:opacity-50"
      >
        {setKey.isPending ? "Saving..." : "Save key"}
      </button>
      <button
        type="button"
        onClick={() => clearKey.mutate()}
        disabled={
          clearKey.isPending ||
          credentials.data?.openai.source !== "credential_store"
        }
        className="rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium disabled:opacity-50"
      >
        Clear
      </button>
    </div>
    {setKey.isError ? (
      <p role="alert" className="mt-[var(--space-2)] text-sm text-danger">
        {(setKey.error as Error).message}
      </p>
    ) : null}
  </section>
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pnpm --dir apps/web test -- SemanticSettings`
Expected: PASS, including the four new cases.

- [ ] **Step 9: Lint, types, build**

Run: `pnpm --dir apps/web lint && pnpm --dir apps/web typecheck && pnpm --dir apps/web build`
Expected: all clean. No `any`.

- [ ] **Step 10: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/queries.ts apps/web/src/features/settings/SemanticSettings.tsx apps/web/src/features/settings/SemanticSettings.test.tsx
git commit -m "feat: enter the OpenAI API key in Settings"
```

---

### Task 8: ADR-0015, documentation, and the gate

**Files:**
- Create: `docs/adr/0015-frontend-credential-entry.md`
- Modify: `docs/adr/README.md`, `docs/operations/backup-and-restore.md`, `docs/operations/answer-generation.md`, `docs/operations/semantic-search.md`, `documentation/architecture.md`, `documentation/design.md`, `documentation/memory.md`, `docs/plans/PLAN.md`, `README.md`

**Interfaces:** none — documentation and verification.

- [ ] **Step 1: Write ADR-0015**

Create `docs/adr/0015-frontend-credential-entry.md` following the structure of `docs/adr/0014-per-repository-embedding-model.md`: Context, Decision, Alternatives, Consequences, Security and Privacy, Migration and Rollback, Approval. Carry these points across from the spec verbatim in substance:

- storage is the Windows Credential Manager, not SQLite, because `create_backup()` copies the database and that is also the file attached to bug reports;
- scope is machine-wide; per-repository opt-in still governs use;
- precedence is credential store → `.env`, matching ADR-0014's ladder;
- the resolved key is never written into `os.environ`, because Git subprocesses inherit it;
- `GET` omits the key entirely rather than masking it, because a suffix is still key material;
- this does **not** protect against a local attacker, and the ADR must say so;
- no migration, `SCHEMA_VERSION` stays 14, `contract_version` stays `1.1`;
- approved by the user on 2026-08-06, referencing `docs/superpowers/specs/2026-08-06-frontend-credential-entry-design.md`.

Add the row to `docs/adr/README.md`.

- [ ] **Step 2: Document the backup consequence**

In `docs/operations/backup-and-restore.md`, add to the section describing what a backup contains:

```markdown
A backup does **not** contain the OpenAI API key. The credential lives in the
Windows Credential Manager, not in the database, so restoring onto a different
machine or user account means entering the key again there (ADR-0015). This is
deliberate: the database is the file most likely to be copied elsewhere or
attached to a support request.
```

- [ ] **Step 3: Update the provider documentation**

In `docs/operations/answer-generation.md` and `docs/operations/semantic-search.md`, replace instructions that say the key must be set in `.env` with: the key may be entered in Settings, where it is stored in the Windows Credential Manager; `.env` still works and is used when nothing is stored; a key set in Settings takes precedence.

- [ ] **Step 4: Update the navigable summaries**

- `documentation/architecture.md` — add `settings/credentials.py` to the module map, add the three endpoints to the API surface list, and state the precedence ladder and the never-in-`os.environ` rule.
- `documentation/design.md` — add the credential field to the Settings component notes: `type="password"`, never populated from the server, its own Save/Clear actions, four states.
- `README.md` — in the `.env` paragraph, note that the OpenAI key can now be entered in Settings instead.

- [ ] **Step 5: Run the full gate**

Run: `powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync`
Expected: exit 0. If `test_the_packaged_web_assets_match_the_source_build` fails, the web app changed — rebuild with `powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1` and re-run.

- [ ] **Step 6: Confirm the contract did not move**

Run: `git grep -n "SCHEMA_VERSION: int" -- src/` and `git grep -n 'contract_version.*1\.' -- src/codeatlas/contracts.py`
Expected: `SCHEMA_VERSION: int = 14` and `1.1`, both unchanged.

- [ ] **Step 7: Append the handoff and update memory**

Append a handoff entry to `docs/plans/PLAN.md` (newest first, never rewriting an earlier entry) recording outcome, files, contracts, exact verification commands with results, limitations, and next step. Update `documentation/memory.md`: add the completed item, add the "never publish a credential to `os.environ`" decision to Decisions Made, and remove the ADR-0015 item from Next Up.

- [ ] **Step 8: Commit**

```bash
git add docs/ documentation/ README.md
git commit -m "docs: record ADR-0015 and frontend credential entry"
```

---

## Self-Review

**Spec coverage.** `CredentialStore` + `UnavailableCredentialStore` → Task 1. `WindowsCredentialStore` (advapi32, `CRED_PERSIST_LOCAL_MACHINE`, `CodeAtlas/` prefix) → Task 2. `resolve_openai_api_key()`, precedence ladder, four read sites, no-`os.environ` rule → Task 3. Machine-wide scope → Task 4 (`CredentialService` takes no repository). Three endpoints, no masking, `max_length=500`, no format validation, the two error codes → Tasks 1 and 5. Frontend `type="password"`, write-only, four states, separate Save/Clear → Task 7. Tests at unit/contract/security/component layers → Tasks 1-7. No migration, `SCHEMA_VERSION` 14, `contract_version` 1.1, backup consequence documented → Tasks 5, 8. Every spec section maps to a task.

**Placeholder scan.** No TBD, TODO, "handle errors appropriately", or "similar to Task N". Every code step carries the actual code. Task 8 Step 1 describes an ADR by required content rather than pasting prose, which is a document to compose, not code to transcribe.

**Type consistency.** `CredentialStore` methods (`is_available`/`get`/`set`/`clear`) take a `name` argument in every definition, implementation, fake, and call. `CredentialStatus` fields (`configured`/`source`/`store_available`) match across the dataclass, the Pydantic response, the TS interface, and every test. `resolve_openai_api_key(store=None)` is called with an argument in Task 4 and without one at the four read sites, which the default supports. `OPENAI_CREDENTIAL_NAME` is the single credential name constant. Source strings are `"credential_store"` and `"env"` everywhere, including the TS union.

One known duplication, deliberate: `_target_name`/`_TARGET_PREFIX` appear in both `credentials.py` and `windows_credentials.py`. Importing the private helper across the module boundary would couple the platform module to the interface module for four characters of string. If a second platform store is ever added, promote it then.

**Verified against the codebase while writing, not assumed:**

- `stubFetch` (`apps/web/src/test/harness.tsx:69`) matches `` `${method} ${url}` `` and falls back to bare `url`, so both key forms in Task 7 work.
- Adding an unconditional `/v1/credentials` call to `SemanticSettings` would have broken **every existing test in its file** with a `NOT_STUBBED` 500. Task 7 therefore updates the shared stub defaults and re-runs the suite *before* any new test is written — otherwise the first failures an implementer sees are unrelated to the feature they are building.
- `sample_repo` is defined in the root `tests/conftest.py:92`, so `tests/security/` receives it.
- `pnpm --dir apps/web` exposes `lint`, `typecheck`, `test`, and `build`; `test` is `vitest run`, so `-- SemanticSettings` filters by filename.
- The four `os.environ` read sites were confirmed at `semantic/providers.py:259` and `:399`, `generation/openai_provider.py:59`, `generation/factory.py:90`.
- `ApplicationServices` is a frozen dataclass, so Task 4 must add the field, the construction, and the keyword argument — all three, or it fails at construction.
