"""Read-only Stage 3D model checks against the currently loaded Gold/Silver builds."""

import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.gold_job import GoldDiagnostics
from src.analytics.context import add_context_arguments, context_from_args
from src.analytics.gold_model import check_model
from src.analytics.gold_specs import V2_SPECS
from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import create_postgres_connection


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transform-version', choices=('v1', 'v2'), default='v1')
    add_context_arguments(parser)
    args = parser.parse_args(argv)
    diagnostics = GoldDiagnostics("Gold model validation", "current_builds/lineage/metrics")
    try:
        with closing(create_clickhouse_client()) as client, closing(create_postgres_connection()) as connection:
            if args.transform_version == 'v1':
                check_model(client, connection, **context_from_args(args))
            else:
                check_model(client, connection, gold_specs=V2_SPECS, **context_from_args(args))
        return 0
    except Exception as error:
        print(diagnostics.failure(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
