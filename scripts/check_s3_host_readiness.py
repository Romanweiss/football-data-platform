"""Explicit read-only host acceptance; no backup, keygen or full-read entry point."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-ca', action='store_true', help='copy public CA certificates only')
    mode.add_argument('--check-source', action='store_true', help='bounded read-only host audit')
    parser.add_argument('--ca-bundle', required=True)
    args = parser.parse_args(argv)
    stage = 'runtime'
    try:
        from src.recovery.runtime import source_container
        from src.recovery.s3_host import prepare_ca, readonly_preflight
        from src.recovery.s3_operator import require_live_runtime
        require_live_runtime()
        stage = 'source-runtime-selection'
        container = source_container('football-airflow-scheduler')
        stage = 'public-ca' if args.prepare_ca else 'bounded-host-source-audit'
        result = (prepare_ca(container, args.ca_bundle) if args.prepare_ca
                  else readonly_preflight(container, args.ca_bundle))
        print(json.dumps(result, sort_keys=True, indent=2))
        # Source acceptance is separate from the intentionally BLOCKED backup/key gate.
        return 0
    except KeyboardInterrupt:
        print('{"status":"INTERRUPTED_NO_BACKUP_CREATED"}', file=sys.stderr)
        return 130
    except Exception as exc:
        # Never format raw SDK/transport errors, command output or environment values.
        from src.recovery.s3_diagnostics import safe_diagnostic
        print(json.dumps({'status': 'FAIL', 'stage': stage, 'error': 'S3_HOST_READINESS_FAILED',
                          'diagnostic': safe_diagnostic(exc)}),
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
