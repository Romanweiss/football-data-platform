"""S3 profile operator CLI. Default: read-only preflight. No dotenv/secret-file discovery."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.recovery import s3_operator as operator
from src.recovery.runtime import RecoveryError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='preflight',
                        choices=('preflight', 'init-directory', 'keygen', 'create', 'verify', 'inspect'))
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--host-ca-bundle', type=Path,
                        help='create only: existing scheduler credentials in memory; public Windows PEM bundle')
    parser.add_argument('--check-source', action='store_true')
    parser.add_argument('--source-bytes', type=int)
    parser.add_argument('--source-objects', type=int)
    parser.add_argument('--expect-source-id')
    parser.add_argument('--expect-inventory-sha256')
    parser.add_argument('--confirm-live-backup', action='store_true')
    parser.add_argument('--confirm-key-recoverable', action='store_true')
    parser.add_argument('--confirm-independent-media', action='store_true')
    parser.add_argument('--confirm-quiet-window', action='store_true')
    parser.add_argument('--confirm-new-private-directory', action='store_true')
    parser.add_argument('--confirm-key-generation', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.host_ca_bundle is not None and args.action != 'create':
            raise RecoveryError('S3_HOST_HANDOFF_CREATE_ONLY')
        if args.action == 'preflight':
            result = operator.preflight(destination=args.destination, key_file=args.key_file, check_source=args.check_source,
                                        source_bytes=args.source_bytes, source_objects=args.source_objects)
        elif args.action == 'create':
            result = operator.create(destination=args.destination, key_file=args.key_file,
                                     expected_source_id=args.expect_source_id,
                                     expected_inventory_sha256=args.expect_inventory_sha256,
                                     confirmed=args.confirm_live_backup, key_recoverable=args.confirm_key_recoverable,
                                     independent_media=args.confirm_independent_media, quiet_window=args.confirm_quiet_window,
                                     host_ca_bundle=args.host_ca_bundle)
        elif args.action in ('verify', 'inspect'):
            result = operator.verify(args.archive, args.key_file)
        else:
            # Explicit local setup only; never called by default/preflight/create.
            from src.recovery.s3_safety import docker_volume_roots, generate_key, prepare_directory
            if args.action == 'init-directory':
                if not args.confirm_new_private_directory:
                    raise RecoveryError('S3_DIRECTORY_CREATION_CONFIRMATION_REQUIRED')
                operator.require_operator_host()
                result = prepare_directory(args.destination, confirmed=True, forbidden_roots=docker_volume_roots())
            else:
                if not args.confirm_key_generation:
                    raise RecoveryError('S3_KEY_GENERATION_CONFIRMATION_REQUIRED')
                operator.require_operator_host()
                result = generate_key(args.key_file, confirmed=True, forbidden_roots=docker_volume_roots())
        print(json.dumps(result, sort_keys=True, indent=2))
        return 1 if result.get('status') == 'BLOCKED' else 0
    except KeyboardInterrupt:
        print('{"status":"INTERRUPTED_PARTIAL_STATE_RETAINED"}', file=sys.stderr)
        return 130
    except Exception as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc) if isinstance(exc, RecoveryError)
                          else 'S3_OPERATOR_FAILED'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
