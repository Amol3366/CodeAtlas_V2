"""The transmitting answer provider: what it sends, and how it fails."""

from __future__ import annotations

import httpx
import pytest

from codeatlas.generation.failures import (
    KeyRejected,
    ProviderUnreachable,
    QuotaExhausted,
)
from codeatlas.generation.openai_provider import OpenAIAnswerProvider
from codeatlas.generation.providers import EvidenceGroundedPrompt, PromptEvidence


def _prompt() -> EvidenceGroundedPrompt:
    return EvidenceGroundedPrompt(
        question="what is this",
        evidence=(
            PromptEvidence(
                evidence_id="ev_1",
                file_path="README.md",
                symbol=None,
                start_line=1,
                end_line=2,
                excerpt="A payments service.",
                derivation="deterministic",
                confidence=1.0,
            ),
        ),
        relation_paths=(),
        warnings=(),
        limitations=(),
    )


def _provider(handler: object) -> OpenAIAnswerProvider:
    return OpenAIAnswerProvider(
        model_id="gpt-4o-mini",
        timeout_seconds=60.0,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
            base_url="https://api.openai.com/v1",
            headers={"Authorization": "Bearer test"},
        ),
    )


def test_a_rejected_key_is_reported_as_key_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    with pytest.raises(KeyRejected):
        list(_provider(handler).generate_stream(_prompt()))


def test_exhausted_quota_is_distinguished_from_ordinary_rate_limiting() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"type": "insufficient_quota", "message": "no credit"}},
        )

    with pytest.raises(QuotaExhausted):
        list(_provider(handler).generate_stream(_prompt()))


def test_ordinary_rate_limiting_is_not_reported_as_exhausted_quota() -> None:
    """The remedies differ: one is 'add credit', the other is 'wait'."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": {"type": "rate_limit_exceeded", "message": "slow down"}}
        )

    with pytest.raises(ProviderUnreachable):
        list(_provider(handler).generate_stream(_prompt()))


def test_streams_the_deltas_openai_sends() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"content":"A payments "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"service."}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body)

    chunks = list(_provider(handler).generate_stream(_prompt()))
    assert "".join(chunks) == "A payments service."


def test_the_request_body_carries_only_evidence_the_caller_supplied() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
        )

    list(_provider(handler).generate_stream(_prompt()))
    body = str(seen["body"])
    assert "README.md" in body
    # No absolute local path is ever part of the payload: evidence carries
    # repository-relative paths, and the repository root is not in the prompt.
    assert "C:\\\\" not in body
    assert "/home/" not in body
