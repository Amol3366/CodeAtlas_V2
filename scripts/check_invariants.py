"""Check the ADR-0016 invariant corpus and write its result artifact.

The Phase 4 baseline measures accuracy, which moves. This checks one boolean
that must not: a weak `TESTS` edge explains a gap rather than closing it.
Weakening it requires editing corpus data AND regenerating a committed
artifact -- two visible acts in one diff.

Usage::

    uv run python scripts/check_invariants.py \\
        --corpus tests/evaluation/invariant_cases \\
        --json-output docs/evaluation/invariants.json \\
        --markdown-output docs/evaluation/invariants.md [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from codeatlas.evaluation.cli import (
    EXIT_INTERNAL_FAILURE,
    EXIT_INVALID_INPUT,
    EXIT_STALE_ARTIFACT,
    EXIT_SUCCESS,
)
from codeatlas.evaluation.invariants import (
    InvariantCorpusError,
    InvariantResult,
    check_corpus,
    load_corpus,
    render_invariant_markdown,
)

# A broken invariant is not a stale artifact and must not share its code: one
# means "regenerate this file", the other means "the product regressed".
EXIT_INVARIANT_BROKEN = 7


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the ADR-0016 invariant corpus."
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare against the tracked artifacts instead of overwriting.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = check_corpus(load_corpus(args.corpus))
        json_text = _result_json(result)
        markdown_text = render_invariant_markdown(result)

        if not result.held:
            for item in result.results:
                for failure in item.failures:
                    print(f"{item.case_id}: {failure}", file=sys.stderr)
            print(
                "ADR-0016 invariant broken. A weak edge must explain a gap,"
                " not close it. See"
                " docs/adr/0016-derivation-tiered-test-edges.md.",
                file=sys.stderr,
            )
            return EXIT_INVARIANT_BROKEN

        if args.check:
            if not (
                _matches(args.json_output, json_text)
                and _matches(args.markdown_output, markdown_text)
            ):
                print(
                    "Invariant artifacts are stale. Regenerate them without"
                    " --check and review the diff.",
                    file=sys.stderr,
                )
                return EXIT_STALE_ARTIFACT
            return EXIT_SUCCESS

        _write(args.json_output, json_text)
        _write(args.markdown_output, markdown_text)
        return EXIT_SUCCESS
    except (InvariantCorpusError, OSError, json.JSONDecodeError) as error:
        print(f"Invalid input: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    except Exception as error:  # pragma: no cover - defensive CLI boundary
        print(f"Internal failure: {error}", file=sys.stderr)
        return EXIT_INTERNAL_FAILURE


def _result_json(result: InvariantResult) -> str:
    return json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _matches(path: Path, expected: str) -> bool:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n") == expected
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
