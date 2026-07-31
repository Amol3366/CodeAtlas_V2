"""Removing credentials from text before it can leave the machine.

`AGENTS.md` Section 4.4 and gate condition 6. This is the one Phase 7 failure
that cannot be undone: a vector can be deleted, a budget refunded, a namespace
rebuilt — a credential posted to a third party is disclosed permanently.

Two design decisions carry the module.

**Redact, do not refuse.** A chunk containing a key is still a chunk somebody
will search for, and refusing to embed it would leave a silent hole in coverage
that nothing reports. The secret is replaced; the surrounding code stays
searchable. The vector is derived from redacted text while the embedding record
is keyed by the *original* content hash — correct, because the vector is
derived data and the hash identifies the content it came from, but worth
knowing when reading `cache.py`.

**A false positive is a real cost.** A detector that fires on
`password = get_password()` would redact a repository into uselessness while
appearing to work, and nobody would notice until search quality had quietly
collapsed. So every generic rule here demands evidence that a *value* is
present — a quoted literal or a high-entropy run — and never fires on an
identifier, a call, or an attribute lookup. When a rule cannot tell, it does
not fire: the specific patterns below carry the weight.

The patterns are deliberately conservative and deliberately incomplete. This is
defence in depth behind the real control, which is that no provider transmits
anything unless the user enabled one for that repository.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

PLACEHOLDER: Final[str] = "[REDACTED]"

# Below this length a "secret" is almost certainly a placeholder like
# `changeme`, and redacting it teaches the reader nothing.
_MIN_SECRET_VALUE_LENGTH: Final[int] = 12


@dataclass(frozen=True)
class RedactionResult:
    """Text safe to transmit, and what had to be removed to make it so.

    ``kinds`` names the *rule* that fired, never the value it matched. A field
    holding the matched text would move the secret out of the provider payload
    and into telemetry, which is the same disclosure with extra steps.
    """

    text: str
    redacted_count: int
    kinds: tuple[str, ...]

    @property
    def had_secrets(self) -> bool:
        return self.redacted_count > 0


# Each rule is (kind, pattern). Order matters only for readability; every rule
# is applied. A rule's group 1, when present, is the part replaced — that lets
# a rule keep its context (`password:`) while removing only the value.
_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        # The block form is unmistakable and worth catching whole: a partial
        # redaction of a private key is still a private key.
        "private_key_block",
        re.compile(
            r"-----BEGIN[ A-Z]*PRIVATE KEY-----.*?-----END[ A-Z]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35,}")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"),
    ),
    (
        # Only the credentials are removed, so the host stays readable and a
        # DSN without a password is untouched.
        "connection_string_credentials",
        re.compile(r"(?<=://)([^\s:@/]+:[^\s:@/]+)(?=@)"),
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]{20,}=*)"),
    ),
    (
        # The generic rule, and the one that could do damage. It requires an
        # assignment *and* a quoted literal of real length: `api_key = load()`
        # and `api_key = settings.key` both have no literal and are left alone.
        "assigned_credential",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|secret|password|passwd|pwd|token"
            r"|access[_-]?key|private[_-]?key|client[_-]?secret)\b"
            r"\s*[:=]\s*"
            r"[\"']([^\"'\n]{" + str(_MIN_SECRET_VALUE_LENGTH) + r",})[\"']"
        ),
    ),
)


def redact(text: str) -> RedactionResult:
    """Replace anything that looks like a credential with ``PLACEHOLDER``.

    Returns the original string unchanged, and a zero count, when nothing
    matched — so a caller can tell "scanned and clean" from "not scanned".
    """
    if not text:
        return RedactionResult(text=text, redacted_count=0, kinds=())

    redacted = text
    count = 0
    kinds: list[str] = []

    for kind, pattern in _RULES:
        # A rule with a capturing group replaces only that group, keeping the
        # context that made it recognisable; a rule without one replaces the
        # whole match.
        replaced, hits = _apply(pattern, redacted)
        if hits:
            redacted = replaced
            count += hits
            kinds.append(kind)

    return RedactionResult(
        text=redacted, redacted_count=count, kinds=tuple(kinds)
    )


def _apply(pattern: re.Pattern[str], text: str) -> tuple[str, int]:
    hits = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal hits
        hits += 1
        if match.re.groups:
            start, end = match.span(1)
            return (
                match.group(0)[: start - match.start()]
                + PLACEHOLDER
                + match.group(0)[end - match.start() :]
            )
        return PLACEHOLDER

    return pattern.sub(replace, text), hits


__all__ = ["PLACEHOLDER", "RedactionResult", "redact"]
