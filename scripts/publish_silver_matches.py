"""Stage 3E: publish the source-aligned matches Silver dimension."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.silver.matches_job import run_job
from src.statsbomb.context import add_bronze_arguments, context_from_args, sha256_argument


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    add_bronze_arguments(parser)
    parser.add_argument("--teams-build-id", required=True, type=sha256_argument)
    args = parser.parse_args(argv)
    return run_job(check_only=args.check_only, **context_from_args(args), parent_sha256=args.parent_sha256, teams_build_id=args.teams_build_id)


if __name__ == "__main__":
    raise SystemExit(main())
