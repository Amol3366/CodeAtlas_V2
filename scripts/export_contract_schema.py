"""Export the versioned CodeAtlas public contract schemas."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from codeatlas.schema_export import schema_bundle_matches, write_schema_bundle

DEFAULT_OUTPUT = Path("docs/api/contract-v1.schema.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Schema output path (default: {DEFAULT_OUTPUT.as_posix()})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero if the tracked schema is missing or stale.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        if schema_bundle_matches(args.output):
            return 0
        print(
            f"Contract schema is stale: {args.output}",
            file=sys.stderr,
        )
        return 1
    write_schema_bundle(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
