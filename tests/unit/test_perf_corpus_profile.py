"""The perf corpus must contain the reference class that dominates real cost.

**This exists because of a measurement that was not merely weak but empty.**
ADR-0062 fitted a resolution scaling exponent of 1.14 on
``measure_phase4_perf.py``'s generated corpus and concluded resolution was
linear. ADR-0064 measured the real repository: ``DOCUMENTS`` is 117,471 of
160,687 references, ``<mention>`` alone is 112,265 (69.9%), and the resolution
cost was **quadratic in mentions x symbols** -- 1,291,272,030 comparisons.

The generated corpus emits ~15-line Python modules and **no Markdown**, so it
has no document sections, no mentions and no routes. The entire quadratic term
was *structurally absent* from the sweep. ADR-0064's conclusion is the one worth
keeping: a clean exponent from a corpus missing the dominant reference class is
not weak evidence, **it is no evidence**.

So the harness now carries a second profile. The synthetic one is kept unchanged
-- the Phase 4 baseline was taken on it and must stay reproducible -- and the
realistic one exists so a scaling claim can be made against a corpus whose
dominant term is present.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.measure_phase4_perf import generate_repository


def _python_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if path.name != "__init__.py"]


def test_the_synthetic_profile_still_emits_no_markdown(tmp_path: Path) -> None:
    """The default is unchanged, because the Phase 4 baseline rests on it.

    This is the regression guard, not an endorsement: the profile's blindness is
    exactly what ADR-0064 found. Changing it would silently move a tracked
    baseline.
    """
    generate_repository(tmp_path, 6)
    assert list(tmp_path.rglob("*.md")) == []


def test_the_realistic_profile_emits_markdown_that_mentions_symbols(
    tmp_path: Path,
) -> None:
    """Markdown alone is not enough -- the mentions are the quadratic term.

    A document with no symbol names in it produces sections and no
    ``<mention>`` references, which is the same blindness in a new costume.
    """
    generate_repository(tmp_path, 6, profile="realistic")

    documents = list(tmp_path.rglob("*.md"))
    assert documents, "the realistic profile must emit Markdown"

    defined = set()
    for path in _python_files(tmp_path):
        source = path.read_text(encoding="utf-8")
        defined.update(re.findall(r"^def (\w+)", source, re.M))
    assert defined, "the realistic profile must still define symbols"

    prose = "\n".join(path.read_text(encoding="utf-8") for path in documents)
    mentioned = {name for name in defined if name in prose}
    assert mentioned, "no document mentions any defined symbol"


def test_the_realistic_profile_emits_materially_larger_modules(
    tmp_path: Path,
) -> None:
    """"Realistic file sizes" is half the row; a 15-line module is not one."""
    synthetic_root = tmp_path / "synthetic"
    realistic_root = tmp_path / "realistic"
    synthetic_root.mkdir()
    realistic_root.mkdir()
    generate_repository(synthetic_root, 6)
    generate_repository(realistic_root, 6, profile="realistic")

    def median_lines(root: Path) -> int:
        counts = sorted(
            len(path.read_text(encoding="utf-8").splitlines())
            for path in _python_files(root)
        )
        return counts[len(counts) // 2]

    assert median_lines(realistic_root) >= 3 * median_lines(synthetic_root)
