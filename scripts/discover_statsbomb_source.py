"""Lightweight catalog/matches discovery. No ingestion, ETL or external notification."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.common.postgres import create_postgres_connection
from src.statsbomb.discovery import discover


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args(argv)
    try:
        with create_postgres_connection() as c:
            print(json.dumps(discover(c,dry_run=args.dry_run),sort_keys=True))
        return 0
    except Exception as exc:
        # Only terminal failures reach this path; downloader retries are internal.
        if not args.dry_run and not getattr(exc,'operation_alert_handled',False):
            from src.alerts.operations import observe_operation
            from src.common.http import DownloadError
            from src.common.source_transport import SourceAccessError
            observe_operation({'step':'source_discovery'},passed=False,
                              source_access=isinstance(exc,(DownloadError,SourceAccessError)))
        print('Source discovery failed: exception=' + type(exc).__name__,file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
