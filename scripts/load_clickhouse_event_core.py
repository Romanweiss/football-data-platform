"""Stage 3A: load only event_core, with immutable-build lineage and recovery."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.job import parse_args, run_job, context_from_args


def main(argv=None) -> int:
    args = parse_args(argv)
    return run_job(**context_from_args(args), check_only=args.check_only, build_id=args.build_id)


if __name__ == "__main__":
    raise SystemExit(main())
