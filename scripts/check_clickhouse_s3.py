"""Read-only Stage 3A smoke: PostgreSQL -> manifest -> ClickHouse s3()."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.job import run_job


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    return run_job(smoke=True)


if __name__ == "__main__":
    raise SystemExit(main())
