"""Operator entry points; defaults are read-only, imports do not require crypto/SDK."""
import hmac
import importlib.util
import os
from pathlib import Path
import shutil
import sys

from src.recovery.runtime import RecoveryError, digest, encoded, require, source_container


def runtime_report():
    # An explicit tested live policy, not an assumption that all CI interpreters
    # support all profiles. Unlike database/Grafana recovery, S3 does not use SQLite.
    return {'python': '.'.join(map(str, sys.version_info[:3])),
            'live_python_supported': sys.version_info[:3] == (3, 12, 14),
            'required_live_python': '3.12.14',
            'dependencies': {n: importlib.util.find_spec(n) is not None for n in ('cryptography', 'boto3')},
            'docker_cli': shutil.which('docker') is not None, 'sqlite_required_for_s3': False,
            'host_runtime': not Path('/.dockerenv').exists() and not Path('/run/.containerenv').exists()}


def require_operator_host():
    require(runtime_report()['host_runtime'], 'S3_OPERATOR_HOST_RUNTIME_REQUIRED')


def require_live_runtime():
    report = runtime_report()
    require_operator_host()
    require(report['live_python_supported'], 'S3_LIVE_REQUIRES_PYTHON_3_12_14')
    require(all(report['dependencies'].values()) and report['docker_cli'], 'S3_LIVE_DEPENDENCIES_MISSING')
    return report


def build_sources():
    """Existing S3 environment/client, existing container-owned PG/CH credentials."""
    from src.common.s3 import create_s3_client
    from src.recovery.s3_metadata import DockerMetadataSource
    from src.recovery.s3_readonly import S3ReadOnly
    names = ('S3_ENDPOINT', 'S3_REGION', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_BUCKET', 'AWS_CA_BUNDLE')
    require(all(os.environ.get(n, '').strip() for n in names), 'S3_OPERATOR_ENVIRONMENT_INCOMPLETE')
    require(Path(os.environ['AWS_CA_BUNDLE']).is_file(), 'S3_OPERATOR_CA_BUNDLE_MISSING')
    source = S3ReadOnly(create_s3_client(), os.environ['S3_BUCKET'].strip())
    metadata = DockerMetadataSource(source_container('football-postgres'), source_container('football-clickhouse'))
    return source, metadata


def preflight(*, destination=None, key_file=None, check_source=False, source_bytes=None, source_objects=None):
    """No writes/chmod/key generation. Estimates are explicitly not fresh inventory."""
    report = {'runtime': runtime_report(), 'status': 'BLOCKED', 'writes_performed': False,
              'live_backup_executed': False, 'independent_storage_verified': False, 'blockers': []}
    runtime = report['runtime']
    if not runtime['live_python_supported']:
        report['blockers'].append('S3_LIVE_REQUIRES_PYTHON_3_12_14')
    if not runtime['host_runtime']:
        report['blockers'].append('S3_OPERATOR_HOST_RUNTIME_REQUIRED')
    if not all(runtime['dependencies'].values()) or not runtime['docker_cli']:
        report['blockers'].append('S3_LIVE_DEPENDENCIES_MISSING')
    report['environment_present'] = {n: bool(os.environ.get(n, '').strip()) for n in
        ('S3_ENDPOINT', 'S3_REGION', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_BUCKET', 'AWS_CA_BUNDLE')}
    if not all(report['environment_present'].values()):
        report['blockers'].append('S3_OPERATOR_ENVIRONMENT_INCOMPLETE')
    if destination is None or key_file is None:
        report['blockers'].append('S3_DESTINATION_AND_SEPARATE_KEY_REQUIRED')
    if not runtime['dependencies']['cryptography']:
        return report
    from src.recovery.s3_safety import check_space, docker_volume_roots, load_key, locations, space_plan
    if check_source:
        require_live_runtime()  # Fail before network IO on an unsupported runtime.
        from src.recovery.s3_dry_run import audit_source
        from src.recovery.s3_lineage import snapshot_digest
        source, metadata = build_sources()
        baseline = metadata.snapshot()
        audit = audit_source(source, baseline)
        require(snapshot_digest(metadata.snapshot()) == snapshot_digest(baseline), 'S3_METADATA_BASELINE_CHANGED')
        source_bytes, source_objects = audit['bytes'], audit['objects']
        report['source_check'] = audit
        report['source_basis'] = 'FRESH_BOUNDED_READ_ONLY_AUDIT'
    elif source_bytes is not None or source_objects is not None:
        require(source_bytes is not None and source_objects is not None, 'S3_SIZE_AND_COUNT_REQUIRED')
        report['source_basis'] = 'OPERATOR_ESTIMATE_NOT_FRESH_INVENTORY'
    if not check_source:
        report['blockers'].append('S3_FRESH_SOURCE_PREFLIGHT_REQUIRED')
    if source_bytes is not None:
        report['plan'] = space_plan(source_bytes, source_objects)
    if destination is not None and key_file is not None:
        try:
            dest, key = locations(destination, key_file, forbidden_roots=docker_volume_roots())
            load_key(key)
            report['key_available'] = True  # No key, path, fingerprint or contents in the report.
            if 'plan' in report:
                report['space'] = check_space(dest, report['plan'])
        except RecoveryError as exc:
            report['blockers'].append(str(exc))
    if not report['blockers']:
        report['status'] = 'PREFLIGHT_PASS_OPERATOR_CONFIRMATIONS_STILL_REQUIRED'
    return report


def create(*, destination, key_file, expected_source_id, expected_inventory_sha256,
           confirmed=False, key_recoverable=False, independent_media=False, quiet_window=False):
    # These gates precede imports, key reads, SDK construction, Docker and all source IO.
    require(confirmed is True and key_recoverable is True and independent_media is True
            and quiet_window is True, 'S3_OPERATOR_CONFIRMATIONS_REQUIRED')
    require(bool(expected_source_id) and isinstance(expected_inventory_sha256, str)
            and len(expected_inventory_sha256) == 64
            and all(c in '0123456789abcdef' for c in expected_inventory_sha256), 'S3_EXPECTED_SOURCE_AND_INVENTORY_REQUIRED')
    require_live_runtime()
    from src.recovery.s3_safety import check_space, docker_volume_roots, load_key, locations, session_permissions, space_plan
    from src.recovery.s3_workflow import backup_live
    roots = docker_volume_roots()
    parent, key_path = locations(destination, key_file, forbidden_roots=roots)
    master_key = load_key(key_path)
    source, metadata = build_sources()
    require(source.identity.resource_id == expected_source_id, 'S3_SOURCE_IDENTITY_MISMATCH')

    def gates(initial, baseline, *, stage):
        locations(parent, key_path, forbidden_roots=roots)
        require(hmac.compare_digest(master_key, load_key(key_path)), 'S3_KEY_CHANGED_DURING_BACKUP')
        require(digest(encoded(initial)) == expected_inventory_sha256, 'S3_PREFLIGHT_INVENTORY_CHANGED')
        check_space(parent, space_plan(sum(v['head']['size_bytes'] for v in initial.values()), len(initial)),
                    sealing=stage == 'seal')

    return backup_live(source, metadata, parent, master_key, confirmed=True, before_write=gates,
                       permission_guard=session_permissions)


def verify(directory, key_file):
    """Offline authenticated safe manifest summary, not a raw decrypted index dump."""
    from src.recovery.s3_safety import assert_private, load_key, locations, safe_path
    from src.recovery.s3_workflow import verify_backup
    directory = safe_path(directory)
    locations(directory.parent, key_file)
    assert_private(directory, children=True)
    return verify_backup(directory, load_key(key_file))
