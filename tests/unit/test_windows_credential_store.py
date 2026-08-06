"""The real Windows Credential Manager, exercised against the real API.

Not mocked. A mocked ctypes call proves only that the mock was called: the
struct layout, the string encoding, and the persistence flag are exactly what
would be wrong, and only the real API can reject them.

Every entry is written under a test-only name and removed in a finally block,
so a failing assertion cannot leave a credential behind on the machine running
the suite.
"""

from __future__ import annotations

import sys

import pytest

from codeatlas.settings.credentials import CredentialStore

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the Windows Credential Manager is Windows-only"
)

TEST_NAME = "CODEATLAS_TEST_CREDENTIAL"
ABSENT_NAME = "CODEATLAS_TEST_NEVER_WRITTEN"


def _store() -> CredentialStore:
    # Imported inside the test so the ctypes structures never load during
    # collection on a platform that cannot use them.
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
    """The blob is UTF-16LE.

    A key is ASCII today, but an encoding that truncated would corrupt
    silently rather than raise, so the round trip is pinned here.
    """
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
    """Idempotent: the caller wants "nothing stored", which already holds."""
    _store().clear(ABSENT_NAME)


def test_reading_an_absent_credential_returns_none() -> None:
    assert _store().get(ABSENT_NAME) is None
