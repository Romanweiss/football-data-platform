"""Read-only Stage 3D model checks against the currently loaded Gold/Silver builds."""

import argparse
import sys
from contextlib import closing
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.gold_job import GoldDiagnostics
from src.analytics.gold_model import check_model
from src.analytics.gold_specs import SPECS
from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import create_postgres_connection


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transform-version', choices=('v1', 'v2'), default='v1')
    args = parser.parse_args(argv)
    diagnostics = GoldDiagnostics("Gold model validation", "current_builds/lineage/metrics")
    try:
        with closing(create_clickhouse_client()) as client, closing(create_postgres_connection()) as connection:
            if args.transform_version == 'v1':
                check_model(client, connection)
            else:
                check_model(client, connection, gold_specs={name:replace(spec,version='v2') for name,spec in SPECS.items()})
        return 0
    except Exception as error:
        print(diagnostics.failure(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
