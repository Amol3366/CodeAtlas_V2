"""A remote model. Every call sends repository excerpts to a third party.

Constructed only by `factory.build_answer_provider`, and reached only for a
repository whose stored policy names it. There is deliberately no environment
variable that enables it: `.env` supplies the credential and the model name,
never the consent — the same boundary `build_embedding_provider` documents.

The excerpts it receives have already been redacted by the caller, and they are
the only repository content in the payload. Paths are repository-relative, so
the local repository root is not part of what leaves the machine.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import httpx

from codeatlas.generation.failures import (
    GenerationTimedOut,
    KeyRejected,
    ModelMissing,
    ProviderUnreachable,
    QuotaExhausted,
)
from codeatlas.generation.prompts import SYSTEM_PROMPT, render_prompt
from codeatlas.generation.providers import (
    ANSWER_PROMPT_VERSION,
    EvidenceGroundedPrompt,
    GeneratedAnswer,
    collect_stream,
)

DEFAULT_MODEL_ID = "gpt-4o-mini"
_BASE_URL = "https://api.openai.com/v1"
_TEMPERATURE = 0.2


class OpenAIAnswerProvider:
    """Generate an answer with a hosted model."""

    prompt_version = ANSWER_PROMPT_VERSION

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model_id = model_id
        self._timeout = timeout_seconds
        self._client = client or httpx.Client(
            base_url=_BASE_URL,
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"
            },
        )

    def generate(self, prompt: EvidenceGroundedPrompt) -> GeneratedAnswer | None:
        text = collect_stream(self.generate_stream(prompt))
        if not text.strip():
            return None
        return GeneratedAnswer(summary=text.strip(), claims=())

    def generate_stream(self, prompt: EvidenceGroundedPrompt) -> Iterator[str]:
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_prompt(prompt)},
            ],
            "stream": True,
            "temperature": _TEMPERATURE,
        }
        try:
            with self._client.stream(
                "POST", "/chat/completions", json=payload, timeout=self._timeout
            ) as response:
                self._raise_for_status(response)
                for line in response.iter_lines():
                    chunk = _chunk_of(line)
                    if chunk:
                        yield chunk
        except httpx.TimeoutException as error:
            raise GenerationTimedOut(str(error)) from error
        except httpx.RequestError as error:
            raise ProviderUnreachable(str(error)) from error

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        response.read()
        if response.status_code == 401:
            raise KeyRejected("The OpenAI key was rejected.")
        if response.status_code == 404:
            raise ModelMissing(f"OpenAI has no model {self.model_id}.")
        if response.status_code == 429 and _is_quota_error(response):
            # Exhausted quota and ordinary rate limiting share a status code and
            # need different remedies: add credit, or wait. Reporting both as
            # "quota exhausted" would send a user to their billing page over a
            # burst they only had to retry.
            raise QuotaExhausted("The OpenAI quota is exhausted.")
        raise ProviderUnreachable(f"OpenAI answered {response.status_code}.")


def _is_quota_error(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, dict) and error.get("type") == "insufficient_quota"


def _chunk_of(line: str) -> str:
    """Read one Server-Sent Events line from the chat-completions stream."""
    if not line.startswith("data:"):
        return ""
    data = line[len("data:") :].strip()
    if not data or data == "[DONE]":
        return ""
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


__all__ = ["DEFAULT_MODEL_ID", "OpenAIAnswerProvider"]
