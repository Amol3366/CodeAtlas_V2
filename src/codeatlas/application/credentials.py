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
        # Trimmed before storing. A pasted key often carries whitespace, and a
        # trailing newline inside an Authorization header fails with no useful
        # message.
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
        application that edited it would be making a change the user did not
        ask for, in a place they did not look.
        """
        self._store.clear(OPENAI_CREDENTIAL_NAME)
        return self.status()


__all__ = [
    "MAX_CREDENTIAL_LENGTH",
    "CredentialService",
    "CredentialStatus",
]
