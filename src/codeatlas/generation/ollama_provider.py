"""A local model, reached over loopback HTTP.

Transmits nothing off the machine, so it needs no budget and no opt-in beyond
being chosen. It is still handed redacted evidence, because the caller redacts
for every provider: a local model can write a secret into an answer that is
then pasted somewhere else.

Failures are told apart rather than lumped together. "Ollama is not running"
and "that model is not pulled" both stop an answer, and they have different
remedies — start a service, or pull a model. A user told only "generation
failed" has to guess which one they have.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from codeatlas.generation.failures import (
    GenerationTimedOut,
    ModelMissing,
    ProviderUnreachable,
)
from codeatlas.generation.prompts import SYSTEM_PROMPT, render_prompt
from codeatlas.generation.providers import (
    ANSWER_PROMPT_VERSION,
    EvidenceGroundedPrompt,
    GeneratedAnswer,
    collect_stream,
)

DEFAULT_MODEL_ID = "llama3.2:3b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"

# Low, because this explains supplied evidence rather than inventing anything.
# Variance in an answer about fixed facts reads as unreliability.
_TEMPERATURE = 0.2


class OllamaAnswerProvider:
    """Generate an answer with a model running on this machine."""

    prompt_version = ANSWER_PROMPT_VERSION

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def generate(self, prompt: EvidenceGroundedPrompt) -> GeneratedAnswer | None:
        text = collect_stream(self.generate_stream(prompt))
        if not text.strip():
            return None
        return GeneratedAnswer(summary=text.strip(), claims=())

    def generate_stream(self, prompt: EvidenceGroundedPrompt) -> Iterator[str]:
        payload = {
            "model": self.model_id,
            "system": SYSTEM_PROMPT,
            "prompt": render_prompt(prompt),
            "stream": True,
            "options": {"temperature": _TEMPERATURE},
        }
        try:
            with self._client.stream(
                "POST",
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=self._timeout,
            ) as response:
                self._raise_for_status(response)
                for line in response.iter_lines():
                    chunk = _chunk_of(line)
                    if chunk:
                        yield chunk
        except httpx.TimeoutException as error:
            raise GenerationTimedOut(str(error)) from error
        except httpx.RequestError as error:
            # No response at all: the service is not listening, or the host is
            # wrong. Distinct from a service that answered with an error.
            raise ProviderUnreachable(str(error)) from error

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 404:
            # Ollama answers 404 when it is running but has not pulled the
            # model. The service is reachable, so this is not unreachability.
            response.read()
            raise ModelMissing(f"Ollama does not have the model {self.model_id}.")
        if response.status_code >= 400:
            response.read()
            raise ProviderUnreachable(f"Ollama answered {response.status_code}.")


def _chunk_of(line: str) -> str:
    """Read one NDJSON line, ignoring anything unparseable.

    A malformed line is not worth failing a whole answer over: the stream ends
    either way, and the assembled text is what gets validated.
    """
    if not line.strip():
        return ""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return ""
    value = payload.get("response")
    return value if isinstance(value, str) else ""


__all__ = ["DEFAULT_BASE_URL", "DEFAULT_MODEL_ID", "OllamaAnswerProvider"]
