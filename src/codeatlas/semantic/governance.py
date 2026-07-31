"""The boundary a transmitting provider is only reachable through.

`AGENTS.md` Section 4.4 and gate condition 6. A local provider needs none of
this — it transmits nothing by construction — so everything here exists for the
moment repository content would otherwise leave the machine.

The wrapper is a provider, which is the point: `EmbeddingProvider` is the only
type the rest of the system knows, so governance cannot be bypassed by calling
"the real one" instead. There is no unwrapped path to a transmitting provider.

Order of operations, and every step is before the network call for the same
reason — a control applied afterwards has already failed:

1. **Redact.** Section 4.4's hard rule. See `redaction.py`.
2. **Check the budgets.** Per-run first (cheap, local), then the month to date.
3. **Call, with bounded retries.** Transient failures only.
4. **Record usage.** Counts, tokens, latency, outcome — success *and* failure.

Telemetry deliberately cannot hold content: `ProviderUsage` has no field a
prompt, an excerpt, or an answer would fit in, and a test asserts the table's
column list to keep it that way.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from codeatlas.domain.errors import CodeAtlasError, ProviderBudgetExceededError
from codeatlas.domain.semantic import ProviderPolicy, ProviderUsage
from codeatlas.semantic.providers import EmbeddingProvider
from codeatlas.semantic.redaction import redact
from codeatlas.storage.sqlite.semantic_stores import ProviderUsageStore

# Rough, and deliberately so. An exact count needs the provider's own tokenizer,
# which would mean importing a model to decide whether to call a model. Four
# characters per token is the widely used approximation for English and code;
# it is used only to *refuse* early, and the recorded figure is the same
# estimate, so a budget is enforced consistently even if it is not exact.
_CHARACTERS_PER_TOKEN = 4

# Backoff between retries, in seconds. Short: this is a local interactive tool,
# and a user waiting on a chat answer would rather have the deterministic result
# than a slow remote one.
_BACKOFF_SECONDS = (0.5, 1.5)


def estimate_tokens(texts: list[str]) -> int:
    """Approximate the tokens a batch will cost.

    Rounds each text up, so a batch of many short strings is never estimated at
    zero — an estimator that returned zero would make every budget infinite.
    """
    return sum(
        (len(text) + _CHARACTERS_PER_TOKEN - 1) // _CHARACTERS_PER_TOKEN
        for text in texts
        if text
    )


class GovernedEmbeddingProvider:
    """A transmitting provider, wrapped in the controls it may not be used without."""

    def __init__(
        self,
        *,
        inner: EmbeddingProvider,
        policy: ProviderPolicy,
        connection: sqlite3.Connection,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._usage = ProviderUsageStore(connection)
        self._now = now
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep
        # Copied rather than exposed through properties, because
        # `EmbeddingProvider` declares these as settable variables and a
        # read-only property does not satisfy that protocol. The wrapper must
        # *be* an `EmbeddingProvider` — that is what makes governance
        # unbypassable — so it matches the declaration exactly.
        self.model_id = inner.model_id
        self.dimensions = inner.dimensions
        self.normalization_version = inner.normalization_version

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._governed("embed_documents", texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        # Queries go through the identical boundary. A user can paste a
        # credential into a chat box as easily as commit one, and a query is
        # the path that reaches a provider without any indexing step in
        # between.
        return self._governed("embed_queries", texts)

    def _governed(self, operation: str, texts: list[str]) -> list[list[float]]:
        safe = [redact(text).text for text in texts]
        estimated = estimate_tokens(safe)
        self._enforce_budgets(estimated)

        started = time.perf_counter()
        # Counted rather than assumed. `_call` may transmit the payload up to
        # `_max_attempts` times, and recording `requests=1` for three real
        # transmissions let a repository exceed its monthly budget by up to 3x
        # while `tokens_since` reported it as within bounds — which defeats the
        # one control standing between an opted-in repository and an unbounded
        # metered account.
        attempts: list[int] = []
        try:
            vectors = self._call(operation, safe, attempts)
        except Exception:
            self._record(
                operation,
                estimated * max(len(attempts), 1),
                started,
                outcome="error",
                requests=max(len(attempts), 1),
            )
            raise
        self._record(
            operation,
            estimated * len(attempts),
            started,
            outcome="success",
            requests=len(attempts),
        )
        return vectors

    def _call(
        self, operation: str, texts: list[str], attempts: list[int]
    ) -> list[list[float]]:
        """Invoke the provider, retrying transient failures a bounded number of times.

        A `CodeAtlasError` is never retried: those are decisions — disabled,
        unavailable, over budget — and repeating the request cannot change one.
        Everything else is treated as transient, which is the safe default for
        a network call whose failure modes are not ours to enumerate.
        """
        method = getattr(self._inner, operation)
        last: Exception | None = None
        for attempt in range(self._max_attempts):
            # Appended before the call: the payload leaves the machine when the
            # call is made, not when it returns, and a timeout is precisely the
            # case where it was sent and no answer came back.
            attempts.append(attempt)
            try:
                result: list[list[float]] = method(texts)
                return result
            except CodeAtlasError:
                raise
            except Exception as error:
                last = error
                if attempt + 1 < self._max_attempts:
                    self._sleep(
                        _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                    )
        assert last is not None
        raise last

    def _enforce_budgets(self, estimated: int) -> None:
        """Refuse before spending, never after.

        Per-run is checked first because it is free: it needs no query, and a
        request that busts it would have busted the month too.
        """
        per_run = self._policy.per_run_token_budget
        if per_run is not None and estimated > per_run:
            raise ProviderBudgetExceededError(
                "This request exceeds the per-run token budget for this"
                " repository.",
                details={
                    "estimated_tokens": str(estimated),
                    "per_run_token_budget": str(per_run),
                },
            )

        monthly = self._policy.monthly_token_budget
        if monthly is None:
            return
        spent = self._usage.tokens_since(
            self._policy.repository_id, since=_month_start(self._now())
        )
        if spent + estimated > monthly:
            raise ProviderBudgetExceededError(
                "This request exceeds the monthly token budget for this"
                " repository.",
                details={
                    "estimated_tokens": str(estimated),
                    "spent_this_month": str(spent),
                    "monthly_token_budget": str(monthly),
                },
            )

    def _record(
        self,
        operation: str,
        tokens: int,
        started: float,
        *,
        outcome: str,
        requests: int,
    ) -> None:
        """Write the usage row. Failures are recorded as loudly as successes.

        An outcome column that only ever reads `success` cannot answer whether
        a provider is healthy, which is most of what this table is for.
        """
        self._usage.record(
            ProviderUsage(
                # An event ID, not a content hash: two identical calls a
                # second apart are two distinct events and must both be
                # recorded, so this follows the `analysis_`/`conv_`
                # convention rather than `stable_hash`.
                usage_id=f"use_{uuid.uuid4().hex}",
                repository_id=self._policy.repository_id,
                operation=operation,
                provider=self._policy.embedding_provider,
                model_id=self._inner.model_id,
                request_count=requests,
                token_count=tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
                outcome=outcome,
                occurred_at=self._now(),
            )
        )


def _month_start(moment: datetime) -> datetime:
    """Midnight UTC on the first of the given month.

    A budget that never reset would refuse forever after the first heavy
    month, which is indistinguishable from the feature being broken.
    """
    return moment.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC
    )


__all__ = ["GovernedEmbeddingProvider", "estimate_tokens"]
