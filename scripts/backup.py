"""Stage 8C opt-in backup CLI. Never load .env/.passes/keys.txt."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.recovery.archive import load_archive, verified_drills
from src.recovery.operations import ROOT, create_backup, restore_drill, restore_plan
from src.recovery.runtime import RecoveryError
from src.recovery import operations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('create', 'verify', 'inspect', 'plan', 'drill'))
    parser.add_argument('--backup-id')
    parser.add_argument('--target', help='New football-drill-<8..24 lowercase alphanumeric> namespace')
    parser.add_argument('--confirm-isolated', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'create':
            result = create_backup()
        else:
            if not args.backup_id:
                parser.error('--backup-id is required')
            if args.action in ('verify', 'inspect'):
                archive, _ = load_archive(ROOT, args.backup_id)
                result = {'backup_id': args.backup_id, 'status': 'VERIFIED',
                    'contexts': archive.manifest['contexts'], 'artifacts': len(archive.manifest['artifacts']),
                    'bytes': sum(a['file_size'] for a in archive.manifest['artifacts']),
                    'restore_status_at_creation': archive.manifest['verification_status'],
                    'verified_drills': verified_drills(archive)}
                if args.action == 'inspect':
                    result.update(files=archive.manifest['artifacts'], build_ids=archive.manifest['build_ids'],
                                  backup_seconds=archive.manifest['backup_seconds'])
            else:
                if not args.target:
                    parser.error('--target is required')
                result = restore_plan(args.backup_id, args.target) if args.action == 'plan' else restore_drill(
                    args.backup_id, args.target, args.confirm_isolated)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'FAIL', 'backup_id': args.backup_id or operations.CURRENT_BACKUP_ID,
                          'stage': operations.CURRENT_STAGE,
                          'error': str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
