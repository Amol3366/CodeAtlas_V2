"""Document reference & normative-language extraction (Blueprint §4.6.3-4.6.4).

Deterministic, heuristic extraction from documentation text:
- code/file/symbol/config references from inline-code spans and markdown links;
- normative keywords (MUST / SHOULD / REQUIRED …);
- ADR section classification (Status / Context / Decision / Consequences).

These feed document-to-code linking in Phase 9; here they are attached to
document chunks so the signals are captured at chunk time.
"""

from __future__ import annotations

import re

_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_FILE_LIKE = re.compile(r"[\w./-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|md|ya?ml|json|toml|sql)\b")
_DIR_LIKE = re.compile(r"(?:[\w-]+/)+")
_SYMBOL_LIKE = re.compile(r"[A-Za-z_]\w*(?:\.\w+)+|[A-Z]\w+")
_CONFIG_KEY = re.compile(r"[A-Z][A-Z0-9_]{2,}|[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")

_NORMATIVE_WORDS = ("MUST NOT", "MUST", "SHOULD NOT", "SHOULD", "REQUIRED", "SHALL", "MAY NOT")


def extract_references(text: str) -> tuple[str, ...]:
    """Return sorted, unique references found in inline-code spans and links."""
    found: set[str] = set()
    for span in _INLINE_CODE.findall(text):
        span = span.strip()
        if (
            _FILE_LIKE.search(span)
            or _DIR_LIKE.fullmatch(span)
            or _SYMBOL_LIKE.fullmatch(span)
            or _CONFIG_KEY.fullmatch(span)
        ):
            found.add(span)
    for link in _MD_LINK.findall(text):
        target = link.strip()
        if _FILE_LIKE.search(target):
            found.add(target)
    return tuple(sorted(found))


def extract_normative(text: str) -> tuple[str, ...]:
    """Return the normative keywords present (longest-match first, de-duplicated)."""
    present: list[str] = []
    seen: set[str] = set()
    for word in _NORMATIVE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text) and word not in seen:
            # Skip a short form already covered by a longer one (MUST within MUST NOT).
            if any(
                word != longer and word in longer and longer in seen for longer in _NORMATIVE_WORDS
            ):
                continue
            present.append(word)
            seen.add(word)
    return tuple(present)


_ADR_SECTIONS = {
    "status": "Status",
    "context": "Context",
    "decision": "Decision",
    "consequence": "Consequences",
    "consequences": "Consequences",
}


def classify_adr_section(heading_text: str) -> str | None:
    key = heading_text.strip().lower()
    for needle, label in _ADR_SECTIONS.items():
        if needle in key:
            return label
    return None


def is_adr_document(normalized_path: str, top_heading: str) -> bool:
    parts = normalized_path.lower().split("/")
    if "adr" in parts:
        return True
    filename = parts[-1] if parts else ""
    if re.match(r"^\d{3,4}[-_]", filename):
        return True
    return bool(re.match(r"adr[-\s]?\d+", top_heading.strip().lower()))
