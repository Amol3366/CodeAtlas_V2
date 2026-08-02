"""Every generation fault names a cause the user can act on."""

from __future__ import annotations

import pytest

from codeatlas.generation.failures import (
    AnswerProviderFailure,
    GenerationTimedOut,
    KeyRejected,
    ModelMissing,
    ProviderUnreachable,
    QuotaExhausted,
)


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (ProviderUnreachable, "GENERATION_PROVIDER_UNREACHABLE"),
        (ModelMissing, "GENERATION_MODEL_MISSING"),
        (KeyRejected, "GENERATION_KEY_REJECTED"),
        (QuotaExhausted, "GENERATION_QUOTA_EXHAUSTED"),
        (GenerationTimedOut, "GENERATION_TIMED_OUT"),
    ],
)
def test_each_failure_carries_its_warning_code(
    failure: type[AnswerProviderFailure], code: str
) -> None:
    assert failure("boom").warning_code == code


def test_every_failure_is_one_catchable_type() -> None:
    assert issubclass(ModelMissing, AnswerProviderFailure)


def test_failure_message_is_not_the_warning_code() -> None:
    """The code goes to the client; the message stays local for diagnostics."""
    assert str(ModelMissing("llama3.2:3b is not pulled")) != "GENERATION_MODEL_MISSING"
