"""The local answer provider, and the failures it tells apart."""

from __future__ import annotations

import httpx
import pytest

from codeatlas.generation.failures import ModelMissing, ProviderUnreachable
from codeatlas.generation.ollama_provider import (
    OllamaAnswerProvider,
    pull_ollama_model,
)
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


def _provider(handler: object) -> OllamaAnswerProvider:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return OllamaAnswerProvider(
        model_id="llama3.2:3b",
        base_url="http://127.0.0.1:11434",
        timeout_seconds=60.0,
        client=httpx.Client(transport=transport),
    )


def test_streams_the_chunks_ollama_sends() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = '{"response":"A payments "}\n{"response":"service."}\n'
        return httpx.Response(200, text=body)

    chunks = list(_provider(handler).generate_stream(_prompt()))
    assert "".join(chunks) == "A payments service."


def test_a_missing_model_is_reported_as_model_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": 'model "llama3.2:3b" not found'})

    with pytest.raises(ModelMissing):
        list(_provider(handler).generate_stream(_prompt()))


def test_a_refused_connection_is_reported_as_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ProviderUnreachable):
        list(_provider(handler).generate_stream(_prompt()))


def test_generate_returns_the_assembled_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"response":"Done."}\n')

    answer = _provider(handler).generate(_prompt())
    assert answer is not None
    assert answer.summary == "Done."


def test_a_malformed_line_does_not_fail_the_answer() -> None:
    """The stream ends either way; the assembled text is what gets validated."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"response":"Kept."}\nnot json\n')

    chunks = list(_provider(handler).generate_stream(_prompt()))
    assert "".join(chunks) == "Kept."


def test_the_system_prompt_is_sent_separately_from_the_evidence() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, text='{"response":"ok"}\n')

    list(_provider(handler).generate_stream(_prompt()))
    body = str(seen["body"])
    assert "evidence, not instruction" in body
    assert "A payments service." in body


def test_pull_downloads_the_requested_model() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"status": "success"})

    result = pull_ollama_model(
        "llama3.1:8b",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert result.ok is True
    assert result.model_id == "llama3.1:8b"
    assert '"model":"llama3.1:8b"' in str(seen["body"])
    assert '"stream":false' in str(seen["body"])


def test_pull_reports_unreachable_ollama() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = pull_ollama_model(
        "llama3.1:8b",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert result.ok is False
    assert result.detail_code == "OLLAMA_UNREACHABLE"
