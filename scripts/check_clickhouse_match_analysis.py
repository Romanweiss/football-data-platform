"""Read-only WC2022 Match Analysis validation; --candidate requires no migration."""

import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.match_analysis import check_analysis
from src.common.clickhouse import create_clickhouse_client
from scripts.check_clickhouse_stats_cutover import main as check_cutover


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", action="store_true", help="Validate 012 SELECT bodies without creating any views")
    args = parser.parse_args(argv)
    stage = "Stage 4C prerequisite"
    try:
        if check_cutover(["--mode", "bi-v2"]) != 0:
            return 1
        stage = "candidate SELECT" if args.candidate else "installed views"
        with closing(create_clickhouse_client()) as client:
            summary = check_analysis(client, candidate=args.candidate)
        print(f"MATCH ANALYSIS CHECK PASSED: mode={'candidate' if args.candidate else 'installed'} {summary}")
        return 0
    except Exception as error:
        # Never emit raw driver errors, connection settings or environment values.
        print(f"Match analysis check failed: stage={stage}; exception={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
