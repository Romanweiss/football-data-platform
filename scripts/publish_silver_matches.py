"""Stage 3E: publish the source-aligned matches Silver dimension."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.silver.matches_job import run_job


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    return run_job(check_only=args.check_only)


if __name__ == "__main__":
    raise SystemExit(main())
