"""What must be true before repository content leaves the machine.

Gate condition 6, minus redaction, which has its own file. The governed wrapper
is the only path a transmitting provider is reachable through, so these tests
are about a boundary rather than a feature: every one of them describes
something that must happen *before* the network call, or something that must
never appear after it.

The wrapper is tested against a fake transport throughout. No test here needs
network access or an API key, which is deliberate — a suite that quietly
skipped without credentials would be a suite that stopped guarding this.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeatlas.domain.errors import ProviderBudgetExceededError
from codeatlas.domain.semantic import EmbeddingProviderKind, ProviderPolicy
from codeatlas.semantic.governance import GovernedEmbeddingProvider, estimate_tokens
from codeatlas.semantic.redaction import PLACEHOLDER
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.storage.sqlite.semantic_stores import ProviderUsageStore

_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)


class RecordingProvider:
    """A transmitting provider, faked. Records exactly what it was handed."""

    model_id = "fake-remote"
    dimensions = 3
    normalization_version = "l2_v1"

    def __init__(self) -> None:
        self.seen: list[list[str]] = []
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.seen.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


class FlakyProvider(RecordingProvider):
    """Fails a declared number of times, then succeeds."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self._remaining = failures

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._remaining > 0:
            self._remaining -= 1
            raise TimeoutError("upstream timed out")
        return super().embed_documents(texts)


@pytest.fixture
def connection(tmp_path: Path):  # type: ignore[no-untyped-def]
    with connect(tmp_path / "db.sqlite") as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO repositories"
            " (repository_id, display_name, canonical_root, created_at)"
            " VALUES ('repo_1', 'demo', 'C:/repos/demo', '2026-07-30T00:00:00Z')"
        )
        yield conn


def _policy(
    *, monthly: int | None = None, per_run: int | None = None
) -> ProviderPolicy:
    return ProviderPolicy(
        repository_id="repo_1",
        embedding_provider=EmbeddingProviderKind.OPENAI,
        monthly_token_budget=monthly,
        per_run_token_budget=per_run,
        updated_at=_NOW,
    )


def _governed(
    connection: sqlite3.Connection,
    inner: object,
    *,
    policy: ProviderPolicy | None = None,
    max_attempts: int = 3,
) -> GovernedEmbeddingProvider:
    return GovernedEmbeddingProvider(
        inner=inner,  # type: ignore[arg-type]
        policy=policy or _policy(),
        connection=connection,
        now=lambda: _NOW,
        max_attempts=max_attempts,
        sleep=lambda _seconds: None,
    )


# --- nothing leaves without passing redaction ----------------------------


def test_a_secret_is_redacted_before_the_provider_sees_it(
    connection: sqlite3.Connection,
) -> None:
    """The ordering is the whole control. Redacting after transmission would
    be theatre."""
    inner = RecordingProvider()

    _governed(connection, inner).embed_documents(
        ["key = AKIAIOSFODNN7EXAMPLE", "def total(): ..."]
    )

    sent = inner.seen[0]
    assert "AKIAIOSFODNN7EXAMPLE" not in "".join(sent)
    assert PLACEHOLDER in sent[0]
    assert sent[1] == "def total(): ..."


def test_a_query_is_redacted_too(connection: sqlite3.Connection) -> None:
    """A user can paste a credential into the chat box as easily as commit
    one, and the query takes a different code path from the documents."""
    inner = RecordingProvider()

    _governed(connection, inner).embed_queries(["is AKIAIOSFODNN7EXAMPLE valid"])

    assert "AKIAIOSFODNN7EXAMPLE" not in "".join(inner.seen[0])


# --- budgets refuse before spending --------------------------------------


def test_a_run_over_its_budget_never_reaches_the_provider(
    connection: sqlite3.Connection,
) -> None:
    """Refusing after the call would have already spent the money."""
    inner = RecordingProvider()
    governed = _governed(connection, inner, policy=_policy(per_run=5))

    with pytest.raises(ProviderBudgetExceededError):
        governed.embed_documents(["a much longer body of text " * 20])

    assert inner.calls == 0


def test_an_exhausted_monthly_budget_refuses(
    connection: sqlite3.Connection,
) -> None:
    inner = RecordingProvider()
    governed = _governed(connection, inner, policy=_policy(monthly=100))
    ProviderUsageStore(connection).record(
        _usage(token_count=100, occurred_at=_NOW)
    )

    with pytest.raises(ProviderBudgetExceededError):
        governed.embed_documents(["anything at all"])

    assert inner.calls == 0


def test_spending_from_an_earlier_month_does_not_count(
    connection: sqlite3.Connection,
) -> None:
    """A monthly budget that never reset would refuse forever."""
    inner = RecordingProvider()
    governed = _governed(connection, inner, policy=_policy(monthly=100))
    ProviderUsageStore(connection).record(
        _usage(token_count=100, occurred_at=datetime(2026, 6, 1, tzinfo=UTC))
    )

    governed.embed_documents(["anything at all"])

    assert inner.calls == 1


def test_no_budget_means_unlimited(connection: sqlite3.Connection) -> None:
    inner = RecordingProvider()

    _governed(connection, inner, policy=_policy()).embed_documents(["text " * 500])

    assert inner.calls == 1


def test_a_budget_refusal_is_not_retried(connection: sqlite3.Connection) -> None:
    """Section 10.3: no retry for validation or deterministic input errors.
    Retrying a budget refusal would burn the retry allowance on a decision
    that cannot change."""
    inner = RecordingProvider()
    governed = _governed(connection, inner, policy=_policy(per_run=1))

    with pytest.raises(ProviderBudgetExceededError):
        governed.embed_documents(["a long enough body of text to exceed one token"])

    assert inner.calls == 0


# --- bounded retries -----------------------------------------------------


def test_a_transient_failure_is_retried(connection: sqlite3.Connection) -> None:
    inner = FlakyProvider(failures=2)

    vectors = _governed(connection, inner).embed_documents(["text"])

    assert len(vectors) == 1
    assert inner.calls == 1


def test_retries_are_bounded(connection: sqlite3.Connection) -> None:
    """Unbounded retry against a provider that is down is how a local tool
    hangs forever and how a metered account is drained."""
    inner = FlakyProvider(failures=99)

    with pytest.raises(TimeoutError):
        _governed(connection, inner, max_attempts=3).embed_documents(["text"])


def test_every_transmitted_attempt_is_billed(connection: sqlite3.Connection) -> None:
    """A retry is another payload on the wire, and the budget has to see it.

    Recording one request for three transmissions let a repository run at up to
    three times its stated monthly budget while the usage table reported it as
    compliant — the budget is the only thing bounding an opted-in repository's
    spend, so under-counting it is the failure that matters.
    """
    inner = FlakyProvider(failures=2)

    _governed(connection, inner).embed_documents(["text"])

    requests, tokens = connection.execute(
        "SELECT SUM(request_count), SUM(token_count) FROM provider_usage"
    ).fetchone()
    assert requests == 3, "two failed attempts were transmitted and not counted"
    assert tokens > 0


def test_a_failed_call_bills_each_attempt_too(connection: sqlite3.Connection) -> None:
    inner = FlakyProvider(failures=99)

    with pytest.raises(TimeoutError):
        _governed(connection, inner, max_attempts=3).embed_documents(["text"])

    requests = connection.execute(
        "SELECT SUM(request_count) FROM provider_usage"
    ).fetchone()[0]
    assert requests == 3


# --- telemetry records counts, never content -----------------------------


def test_a_successful_call_is_recorded(connection: sqlite3.Connection) -> None:
    _governed(connection, RecordingProvider()).embed_documents(["hello world"])

    rows = connection.execute(
        "SELECT operation, provider, model_id, request_count, token_count,"
        " outcome FROM provider_usage"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "success"
    assert rows[0]["provider"] == "openai"
    assert rows[0]["token_count"] > 0


def test_a_failure_is_recorded_too(connection: sqlite3.Connection) -> None:
    """An outcome column that only ever says "success" cannot answer whether a
    provider is healthy."""
    with pytest.raises(TimeoutError):
        _governed(
            connection, FlakyProvider(failures=99), max_attempts=2
        ).embed_documents(["text"])

    row = connection.execute(
        "SELECT outcome FROM provider_usage"
    ).fetchone()
    assert row is not None
    assert row["outcome"] == "error"


def test_the_usage_table_has_nowhere_to_put_content(
    connection: sqlite3.Connection,
) -> None:
    """A schema review, asserted. Section 17 forbids recording source,
    prompts, excerpts, or answers; the strongest form of that guarantee is a
    table with no column such a value would fit in."""
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(provider_usage)")
    }

    assert columns == {
        "usage_id",
        "repository_id",
        "operation",
        "provider",
        "model_id",
        "request_count",
        "token_count",
        "latency_ms",
        "outcome",
        "occurred_at",
    }


def test_the_recorded_text_is_nowhere_in_the_database(
    connection: sqlite3.Connection,
) -> None:
    """The end-to-end version of the schema review."""
    _governed(connection, RecordingProvider()).embed_documents(
        ["a distinctive phrase nobody else would write"]
    )

    dumped = "\n".join(connection.iterdump())
    assert "distinctive phrase" not in dumped


# --- token estimation ----------------------------------------------------


def test_token_estimation_grows_with_text() -> None:
    assert estimate_tokens(["short"]) < estimate_tokens(["a much longer text " * 10])


def test_token_estimation_of_nothing_is_zero() -> None:
    assert estimate_tokens([]) == 0


def _usage(*, token_count: int, occurred_at: datetime):  # type: ignore[no-untyped-def]
    from codeatlas.domain.semantic import ProviderUsage

    return ProviderUsage(
        usage_id=f"use_{occurred_at.isoformat()}",
        repository_id="repo_1",
        operation="embed_documents",
        provider=EmbeddingProviderKind.OPENAI,
        model_id="fake-remote",
        request_count=1,
        token_count=token_count,
        latency_ms=1,
        outcome="success",
        occurred_at=occurred_at,
    )
