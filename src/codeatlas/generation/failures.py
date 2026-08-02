"""Why generation did not happen, in terms a user can act on.

One catchable base class, because `explanations.py` treats every fault
identically — fall back to the verified answer — and differs only in the code it
reports. The message stays local for diagnostics; the ``warning_code`` is what
reaches the client, because a provider's own message can quote the request that
produced it, and that request is repository content.

The causes are told apart rather than lumped together because their remedies
differ. "Ollama is not running" and "that model is not pulled" both surface as
a failure to generate, and a user told only "generation failed" has to guess
which one they have.
"""

from __future__ import annotations


class AnswerProviderFailure(Exception):
    """A provider could not produce an answer. Never fatal to a run."""

    warning_code: str = "ANSWER_GENERATION_FAILED"


class ProviderUnreachable(AnswerProviderFailure):
    """No server answered. Ollama is not running, or the host is wrong."""

    warning_code = "GENERATION_PROVIDER_UNREACHABLE"


class ModelMissing(AnswerProviderFailure):
    """The server answered, but does not have that model."""

    warning_code = "GENERATION_MODEL_MISSING"


class KeyRejected(AnswerProviderFailure):
    """The credential was refused."""

    warning_code = "GENERATION_KEY_REJECTED"


class QuotaExhausted(AnswerProviderFailure):
    """The account has no remaining quota."""

    warning_code = "GENERATION_QUOTA_EXHAUSTED"


class GenerationTimedOut(AnswerProviderFailure):
    """The model did not finish inside the configured bound."""

    warning_code = "GENERATION_TIMED_OUT"


__all__ = [
    "AnswerProviderFailure",
    "GenerationTimedOut",
    "KeyRejected",
    "ModelMissing",
    "ProviderUnreachable",
    "QuotaExhausted",
]
