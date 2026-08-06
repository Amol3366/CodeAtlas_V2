"""Which model answers for one repository.

The stored policy is the only thing that decides *whether* generation happens.
The environment decides only *which* model runs when it does. That split is the
same one `build_embedding_provider` documents, and it is what stops a stray
variable — in a shell, in `.env`, in CI — from turning a repository that opted
into nothing into one that generates, or transmits.

Precedence for model identity, most specific first:

    stored per-repository setting -> environment default -> built-in default

The per-repository setting wins because it is the more deliberate act: someone
chose it for this repository, in the app, rather than for the machine.
"""

from __future__ import annotations

from codeatlas.domain.semantic import AnswerProviderKind, ProviderPolicy
from codeatlas.generation.ollama_provider import DEFAULT_BASE_URL, OllamaAnswerProvider
from codeatlas.generation.ollama_provider import (
    DEFAULT_MODEL_ID as OLLAMA_DEFAULT_MODEL,
)
from codeatlas.generation.openai_provider import (
    DEFAULT_MODEL_ID as OPENAI_DEFAULT_MODEL,
)
from codeatlas.generation.openai_provider import OpenAIAnswerProvider
from codeatlas.generation.providers import AnswerProvider, NoAnswerProvider
from codeatlas.settings.credentials import resolve_openai_api_key
from codeatlas.settings.env_file import (
    configured_answer_timeout_seconds,
    configured_ollama_answer_model,
    configured_ollama_base_url,
    configured_openai_answer_model,
)

# Generous, because the primary provider is a local model and a large one on a
# CPU legitimately takes minutes. A bound tuned to the 3B default would make
# "use a bigger model for deeper reasoning" fail on every question, which is the
# feature appearing broken exactly when it is used as intended.
DEFAULT_TIMEOUT_SECONDS = 120.0

OPENAI_API_KEY_VARIABLE = "OPENAI_API_KEY"


def build_answer_provider(policy: ProviderPolicy) -> AnswerProvider:
    """Return the provider one repository's policy selects."""
    timeout = float(
        policy.answer_timeout_seconds
        or configured_answer_timeout_seconds()
        or DEFAULT_TIMEOUT_SECONDS
    )

    if policy.answer_provider is AnswerProviderKind.OLLAMA:
        return OllamaAnswerProvider(
            model_id=policy.answer_model
            or configured_ollama_answer_model()
            or OLLAMA_DEFAULT_MODEL,
            base_url=configured_ollama_base_url() or DEFAULT_BASE_URL,
            timeout_seconds=timeout,
        )

    if policy.answer_provider is AnswerProviderKind.OPENAI:
        return OpenAIAnswerProvider(
            model_id=policy.answer_model
            or configured_openai_answer_model()
            or OPENAI_DEFAULT_MODEL,
            timeout_seconds=timeout,
        )

    return NoAnswerProvider()


def describe_available_answer_providers() -> dict[AnswerProviderKind, bool]:
    """Which answer providers could run here, without constructing any.

    Ollama is reported available whenever it is configurable at all, rather
    than by connecting to it. Proving availability would put a network call
    behind rendering a settings page, and a page that is slow because a service
    is *absent* is a poor way to tell someone the service is absent. The
    settings page says "requires Ollama"; the first real question reports
    `GENERATION_PROVIDER_UNREACHABLE` if it is not there. That order is both
    cheap and honest.
    """
    return {
        AnswerProviderKind.NONE: True,
        AnswerProviderKind.OLLAMA: True,
        # Resolved through the credential store as well as `.env` (ADR-0015),
        # so a key saved in Settings enables the option without a restart.
        AnswerProviderKind.OPENAI: bool((resolve_openai_api_key() or "").strip()),
    }


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "OPENAI_API_KEY_VARIABLE",
    "build_answer_provider",
    "describe_available_answer_providers",
]
