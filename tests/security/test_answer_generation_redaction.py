"""Secrets in evidence never reach an answer provider.

Evidence excerpts are raw source, and raw source contains secrets. Redaction is
applied for *every* provider, not only the transmitting one: a local model can
write a secret into an answer that is then copied into a ticket, a chat, or a
pull request.

What is redacted is the prompt, not the response. The evidence drawer still
shows the real line, because that is the user's own file on the user's own
machine — the boundary being defended is the one a model sits behind.
"""

from __future__ import annotations

from collections.abc import Iterator

from codeatlas.contracts import (
    Answer,
    Claim,
    Derivation,
    Evidence,
    EvidenceValidation,
    QueryResponse,
    SnapshotFreshness,
    SnapshotReference,
)
from codeatlas.generation.explanations import EvidenceGroundedExplanationService
from codeatlas.generation.providers import EvidenceGroundedPrompt, GeneratedAnswer

SECRET = "sk-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"


def _response_with_secret() -> QueryResponse:
    evidence = Evidence(
        evidence_id="ev_1",
        repository_id="repo_1",
        snapshot_id="snap_1",
        file_path="src/config.py",
        symbol="settings",
        start_line=1,
        end_line=2,
        excerpt=f'OPENAI_API_KEY = "{SECRET}"',
        content_hash="hash_1",
        derivation=Derivation.DETERMINISTIC,
        confidence=1.0,
        validation=EvidenceValidation.VALID,
    )
    return QueryResponse(
        request_id="req_1",
        repository_id="repo_1",
        snapshot=SnapshotReference(
            snapshot_id="snap_1",
            git_head=None,
            working_tree_fingerprint="fp",
            freshness=SnapshotFreshness.FRESH,
            semantic_coverage=0.0,
        ),
        answer=Answer(
            summary="Found one location.",
            claims=[
                Claim(
                    claim_id="c1",
                    text="The key is configured in config.py.",
                    derivation=Derivation.DETERMINISTIC,
                    confidence=1.0,
                    evidence_ids=["ev_1"],
                )
            ],
        ),
        evidence=[evidence],
    )


class _Capturing:
    """Records exactly what a provider would transmit."""

    model_id = "capturing-test-model"
    prompt_version = "v1"

    def __init__(self) -> None:
        self.seen = ""

    def generate(self, prompt: EvidenceGroundedPrompt) -> GeneratedAnswer | None:
        self.seen = "".join(item.excerpt for item in prompt.evidence)
        return GeneratedAnswer(summary="A configuration file.", claims=())

    def generate_stream(self, prompt: EvidenceGroundedPrompt) -> Iterator[str]:
        self.seen = "".join(item.excerpt for item in prompt.evidence)
        yield "A configuration file."


def test_a_secret_in_an_excerpt_never_reaches_the_provider() -> None:
    provider = _Capturing()

    EvidenceGroundedExplanationService(provider).explain(
        _response_with_secret(), question="what is the key"
    )

    assert SECRET not in provider.seen
    assert "REDACTED" in provider.seen


def test_redaction_applies_on_the_streaming_path_too() -> None:
    """The streaming path is the one a user actually hits in the browser."""
    provider = _Capturing()

    EvidenceGroundedExplanationService(provider).explain(
        _response_with_secret(),
        question="what is the key",
        on_token=lambda _chunk: None,
    )

    assert SECRET not in provider.seen


def test_the_returned_evidence_still_shows_the_real_line() -> None:
    """Redaction defends the provider boundary, not the user's own screen."""
    original = _response_with_secret()

    result = EvidenceGroundedExplanationService(_Capturing()).explain(
        original, question="what is the key"
    )

    assert SECRET in result.evidence[0].excerpt
