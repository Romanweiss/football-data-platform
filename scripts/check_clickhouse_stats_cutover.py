"""Read-only shadow validation and explicit BI v1/v2 verification. No S3 calls."""
import argparse
import json
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analytics.stats_cutover import audited_state, validate_shadow, validate_bi
from src.analytics.gold_model import check_model
from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import create_postgres_connection
from scripts.check_clickhouse_match_results import main as check_results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("shadow", "bi-v2", "bi-v1"), required=True)
    args = parser.parse_args(argv)
    try:
        audit = json.loads((ROOT / "docs/stage4b_shot_audit.json").read_text(encoding="utf-8"))
        if check_results([]) != 0:
            raise RuntimeError("Match results prerequisite failed")
        with closing(create_clickhouse_client()) as client, closing(create_postgres_connection()) as connection:
            before = audited_state(client, connection, audit, shadow=args.mode != "bi-v1")
            if args.mode == "bi-v1":
                check_model(client, connection)
            else:
                validate_shadow(client, connection, audit)
            if args.mode != "shadow":
                validate_bi(client, version=args.mode[-2:])
            if before != audited_state(client, connection, audit, shadow=args.mode != "bi-v1"):
                raise RuntimeError("Serving state changed during check")
        print(f"STATS CUTOVER CHECK PASSED: mode={args.mode}")
        return 0
    except Exception as error:
        print(f"Stats cutover check failed: mode={args.mode} exception={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
