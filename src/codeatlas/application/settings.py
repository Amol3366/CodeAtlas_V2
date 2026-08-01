"""Turning a provider on, and describing what could be turned on.

Section 12.5's settings surface. Everything the semantic layer contains is inert
until a provider policy is written, so this module is where that decision is
made — and therefore the last place a mistake is still cheap. After it,
repository content is being sent somewhere.

Three rules make "opt-in" mean opt-in:

**Absence is `none`.** A missing policy row resolves to no provider, so a failed
write, a partial restore, or an upgrade cannot become a disclosure.

**A partial update changes only what it names.** Every field is a sentinel-
guarded option rather than a value with a default, because a PATCH that reset
unmentioned fields would let someone lower a budget by editing a provider.

**A transmitting provider must carry a monthly budget.** `ProviderPolicy`
documents that an unlimited budget is only ever reachable for a provider that
does not transmit; this is the layer that enforces the pairing, at enable time
*and* on every later edit. An unbounded metered account is how a local tool
produces a surprising bill.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from codeatlas.domain.errors import InvalidRequestError, RepositoryNotFoundError
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.storage.sqlite.semantic_stores import ProviderPolicyStore
from codeatlas.storage.sqlite.stores import RepositoryStore

# Distinguishes "not mentioned" from "set to null". Without it, PATCH cannot
# express clearing a budget, and every unmentioned field would silently reset.
_UNSET: Final = object()


@dataclass(frozen=True)
class RepositorySettings:
    """One repository's provider decision, as stored."""

    repository_id: str
    embedding_provider: EmbeddingProviderKind
    monthly_token_budget: int | None
    per_run_token_budget: int | None
    updated_at: datetime

    @property
    def transmits_off_machine(self) -> bool:
        return self.embedding_provider.transmits_off_machine


@dataclass(frozen=True)
class ModelDescriptor:
    """One provider a user could choose, and what choosing it means.

    Carries no credential, by having nowhere to put one. The settings surface
    reads this, and Section 12.5 forbids a secret appearing in a GET response.
    """

    provider: EmbeddingProviderKind
    model_id: str | None
    dimensions: int | None
    available: bool
    transmits_off_machine: bool
    # What is missing when `available` is false — an extra to install or a
    # variable to set. A settings page can then explain an unavailable option
    # instead of hiding it, which is the difference between a product that
    # looks broken and one that tells you what to do.
    requires: str | None


@dataclass(frozen=True)
class ProviderTestResult:
    """Whether the configured provider actually answers.

    ``detail_code`` is a code, never a provider message: a message can quote
    the request that produced it, and for a transmitting provider that request
    is repository content.
    """

    provider: EmbeddingProviderKind
    ok: bool
    detail_code: str | None
    latency_ms: int


class SettingsService:
    """Read and change one repository's provider policy."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connection = connection
        self._repositories = RepositoryStore(connection)
        self._policies = ProviderPolicyStore(connection)
        self._now = now

    def get(self, repository_id: str) -> RepositorySettings:
        self._require_repository(repository_id)
        return _from_policy(self._policies.get(repository_id))

    def update(
        self,
        repository_id: str,
        *,
        embedding_provider: EmbeddingProviderKind | None = None,
        monthly_token_budget: int | None = None,
        per_run_token_budget: int | None = None,
        clear_monthly: bool = False,
        clear_per_run: bool = False,
    ) -> RepositorySettings:
        """Apply a partial change, refusing anything that would leave it unsafe.

        ``clear_monthly`` and ``clear_per_run`` exist because ``None`` already
        means "not mentioned" here. Without them a caller could not distinguish
        "leave the budget alone" from "remove the budget", and one of those is
        a spending decision.
        """
        self._require_repository(repository_id)
        current = self._policies.get(repository_id)

        provider = (
            current.embedding_provider
            if embedding_provider is None
            else embedding_provider
        )
        monthly = _resolve(
            current.monthly_token_budget, monthly_token_budget, clear_monthly
        )
        per_run = _resolve(
            current.per_run_token_budget, per_run_token_budget, clear_per_run
        )

        for label, value in (("monthly", monthly), ("per_run", per_run)):
            if value is not None and value < 0:
                raise InvalidRequestError(
                    f"The {label} token budget cannot be negative.",
                    details={"field": f"{label}_token_budget"},
                )

        if provider.transmits_off_machine and monthly is None:
            # Checked against the *resolved* state rather than the request, so
            # removing the budget later is refused exactly like never setting
            # one. Both routes reach the same unbounded account.
            raise InvalidRequestError(
                "A provider that sends content off the machine requires a"
                " monthly token budget.",
                details={
                    "provider": provider.value,
                    "field": "monthly_token_budget",
                },
            )

        policy = ProviderPolicy(
            repository_id=repository_id,
            embedding_provider=provider,
            monthly_token_budget=monthly,
            per_run_token_budget=per_run,
            updated_at=self._now(),
        )
        self._policies.set(policy)
        return _from_policy(policy)

    def models(self) -> tuple[ModelDescriptor, ...]:
        """Every provider, including the ones that cannot run here.

        Listing the unavailable ones is deliberate: a settings page that hides
        an option cannot explain why it is missing, and "install the extra" is
        the whole answer for most users who go looking.
        """
        from codeatlas.domain.errors import CodeAtlasError
        from codeatlas.semantic.providers import (
            LOCAL_MODEL_DIMENSIONS,
            LOCAL_MODEL_ID,
            OPENAI_API_KEY_VARIABLE,
            describe_available_providers,
            resolve_local_embedding_model,
            resolve_openai_embedding_model,
        )

        available = describe_available_providers()
        local_model = resolve_local_embedding_model()
        openai_model: str | None
        openai_dimensions: int | None
        try:
            openai_model, openai_dimensions = resolve_openai_embedding_model()
            openai_requires: str | None = None
        except CodeAtlasError as error:
            # A misconfigured custom model is reported the same way a missing
            # extra is: the option stays visible and explains itself, rather
            # than disappearing or crashing the settings page.
            openai_model, openai_dimensions = None, None
            openai_requires = error.message

        return (
            ModelDescriptor(
                provider=EmbeddingProviderKind.NONE,
                model_id=None,
                dimensions=None,
                available=True,
                transmits_off_machine=False,
                requires=None,
            ),
            ModelDescriptor(
                provider=EmbeddingProviderKind.LOCAL,
                model_id=local_model,
                # Known only for the pinned model. Loading a custom one to
                # measure it is exactly the cost this function avoids.
                dimensions=(
                    LOCAL_MODEL_DIMENSIONS if local_model == LOCAL_MODEL_ID else None
                ),
                available=available[EmbeddingProviderKind.LOCAL],
                transmits_off_machine=False,
                requires=(
                    None
                    if available[EmbeddingProviderKind.LOCAL]
                    else "extra:semantic-local"
                ),
            ),
            ModelDescriptor(
                provider=EmbeddingProviderKind.OPENAI,
                model_id=openai_model,
                dimensions=openai_dimensions,
                available=(
                    available[EmbeddingProviderKind.OPENAI]
                    and openai_requires is None
                ),
                transmits_off_machine=True,
                requires=(
                    openai_requires
                    if openai_requires is not None
                    else (
                        None
                        if available[EmbeddingProviderKind.OPENAI]
                        else f"extra:semantic-openai and {OPENAI_API_KEY_VARIABLE}"
                    )
                ),
            ),
        )

    def test_provider(self, repository_id: str) -> ProviderTestResult:
        """Ask the configured provider to embed one short string.

        Uses the repository's own policy rather than a supplied one, so the
        thing tested is the thing that will run. The probe text is a fixed
        literal and never repository content: a connectivity check is not a
        reason to transmit source.
        """
        import time

        self._require_repository(repository_id)
        policy = self._policies.get(repository_id)
        if policy.embedding_provider is EmbeddingProviderKind.NONE:
            return ProviderTestResult(
                provider=policy.embedding_provider,
                ok=False,
                detail_code="PROVIDER_DISABLED",
                latency_ms=0,
            )

        from codeatlas.semantic.providers import ProviderFactory

        started = time.perf_counter()
        try:
            provider = ProviderFactory(self._connection).build(policy)
            vectors = provider.embed_queries(["connectivity probe"])
        except Exception as error:
            return ProviderTestResult(
                provider=policy.embedding_provider,
                ok=False,
                detail_code=_failure_code(error),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        elapsed = int((time.perf_counter() - started) * 1000)
        if not vectors or not vectors[0]:
            return ProviderTestResult(
                provider=policy.embedding_provider,
                ok=False,
                detail_code="PROVIDER_RETURNED_NO_VECTOR",
                latency_ms=elapsed,
            )
        return ProviderTestResult(
            provider=policy.embedding_provider,
            ok=True,
            detail_code=None,
            latency_ms=elapsed,
        )

    def _require_repository(self, repository_id: str) -> None:
        if self._repositories.get(repository_id) is None:
            raise RepositoryNotFoundError("The repository is not registered.")


def _resolve(current: int | None, requested: int | None, clear: bool) -> int | None:
    if clear:
        return None
    return current if requested is None else requested


def _from_policy(policy: ProviderPolicy) -> RepositorySettings:
    return RepositorySettings(
        repository_id=policy.repository_id,
        embedding_provider=policy.embedding_provider,
        monthly_token_budget=policy.monthly_token_budget,
        per_run_token_budget=policy.per_run_token_budget,
        updated_at=policy.updated_at,
    )


def _failure_code(error: Exception) -> str:
    """Reduce a failure to a code.

    A provider's own message can quote the payload that caused it, and for a
    transmitting provider that payload is repository content.
    """
    code = getattr(error, "code", None)
    if code is not None:
        return str(getattr(code, "value", code))
    return "PROVIDER_TEST_FAILED"


__all__ = [
    "ModelDescriptor",
    "ProviderTestResult",
    "RepositorySettings",
    "SettingsService",
]
