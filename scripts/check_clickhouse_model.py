"""Read-only Silver/Gold references including the Stage 3E match dimension."""

import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.job import LoadDiagnostics
from src.analytics.matches_model import check_model
from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import create_postgres_connection


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    diagnostics = LoadDiagnostics("model validation", "current_builds/references")
    try:
        with closing(create_clickhouse_client()) as client, closing(create_postgres_connection()) as connection:
            check_model(client, connection)
        return 0
    except Exception as error:
        print(diagnostics.failure(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
