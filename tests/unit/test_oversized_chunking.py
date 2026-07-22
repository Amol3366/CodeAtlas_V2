"""Oversized-symbol splitting: exact, unbroken line mapping (Blueprint §4.5.3)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from codeatlas.chunking.code_chunker import CodeChunker
from codeatlas.chunking.oversized_symbol import partition_by_tokens
from codeatlas.domain.enums import ChunkRole, Language
from codeatlas.parsing.contracts import ParseRequest
from codeatlas.parsing.python.parser import PythonParser


@given(
    start=st.integers(min_value=1, max_value=50),
    length=st.integers(min_value=0, max_value=400),
    target=st.integers(min_value=1, max_value=200),
)
def test_partition_covers_range_contiguously(start: int, length: int, target: int) -> None:
    end = start + length
    lines = ["token token token\n"] * (end + 1)
    parts = partition_by_tokens(lines, start, end, target)

    assert parts[0][0] == start
    assert parts[-1][1] == end
    for a, b in parts:
        assert a <= b and start <= a and b <= end
    for (_, b), (c, _) in zip(parts, parts[1:], strict=False):
        assert b + 1 == c  # contiguous, no gaps or overlaps


def test_large_symbol_splits_with_intact_line_mapping() -> None:
    body = "\n".join(f"    total += {i}" for i in range(2000))
    source = f"def big():\n    total = 0\n{body}\n    return total\n"
    result = PythonParser().parse(ParseRequest("r", "big.py", Language.PYTHON, source.encode()))
    chunks = CodeChunker().chunk(result, source, "r")

    parts = sorted(
        (c for c in chunks if c.chunk_role is ChunkRole.OVERSIZED_SYMBOL_PART),
        key=lambda c: c.start_line,
    )
    assert len(parts) > 1  # actually split

    big = next(s for s in result.symbols if s.qualified_name == "big")
    assert parts[0].start_line == big.start_line
    assert parts[-1].end_line == big.end_line
    for earlier, later in zip(parts, parts[1:], strict=False):
        assert earlier.end_line + 1 == later.start_line

    # Concatenated part raw content reconstructs the symbol's exact source.
    lines = source.splitlines(keepends=True)
    expected = "".join(lines[big.start_line - 1 : big.end_line])
    assert "".join(p.raw_content for p in parts) == expected
