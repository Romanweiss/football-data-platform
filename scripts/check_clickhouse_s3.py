"""Read-only Stage 3A smoke: PostgreSQL -> manifest -> ClickHouse s3()."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.job import run_job, parse_args, context_from_args


def main(argv=None) -> int:
    args = parse_args(argv)
    return run_job(smoke=True, build_id=args.build_id, **context_from_args(args))


if __name__ == "__main__":
    raise SystemExit(main())
