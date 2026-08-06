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
