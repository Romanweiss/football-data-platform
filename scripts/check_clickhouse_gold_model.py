"""Read-only Stage 3D model checks against the currently loaded Gold/Silver builds."""

import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.gold_job import GoldDiagnostics
from src.analytics.gold_model import check_model
from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import create_postgres_connection


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    diagnostics = GoldDiagnostics("Gold model validation", "current_builds/lineage/metrics")
    try:
        with closing(create_clickhouse_client()) as client, closing(create_postgres_connection()) as connection:
            check_model(client, connection)
        return 0
    except Exception as error:
        print(diagnostics.failure(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
