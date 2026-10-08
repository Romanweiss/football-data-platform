"""Evaluate persisted DQ, inspect alert state or explicitly dispatch local notifications."""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.common.postgres import create_postgres_connection
from src.alerts.store import evaluate, dispatch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution-id',type=UUID)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--dispatch',action='store_true')
    parser.add_argument('--provider',default='log')
    args = parser.parse_args(argv)
    try:
        with create_postgres_connection() as c:
            result = {}
            if args.execution_id:
                result['evaluation'] = evaluate(c,str(args.execution_id),dry_run=args.dry_run)
            if args.dispatch:
                result['delivery'] = dispatch(c,provider=args.provider,dry_run=args.dry_run)
            with c.transaction(), c.cursor() as cur:
                cur.execute('SELECT status,count(*) FROM metadata.alerts GROUP BY status ORDER BY status')
                result['incidents'] = dict(cur.fetchall())
                cur.execute('SELECT delivery_status,count(*) FROM metadata.alert_delivery_events GROUP BY delivery_status')
                result['delivery_events'] = dict(cur.fetchall())
            print(json.dumps(result,sort_keys=True))
            return 1 if result.get('delivery',{}).get('failed') else 0
    except Exception as exc:
        print('Alert command failed: exception=' + type(exc).__name__,file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
