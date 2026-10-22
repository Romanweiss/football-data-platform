"""Opt-in host read-only audit using captured, process-local container credentials.

Single-threaded operator process only. This is not a secret store or a backup
launcher. Docker access already grants access to the source runtime credentials.
"""
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import ssl

from src.recovery import runtime
from src.recovery.runtime import require
from src.recovery.s3_archive import _no_links
from src.recovery.s3_workflow import guarded

NAMES = ('S3_ENDPOINT', 'S3_REGION', 'S3_BUCKET', 'S3_ACCESS_KEY', 'S3_SECRET_KEY')
ENVIRONMENT = NAMES + ('AWS_CA_BUNDLE',)
PUBLIC_CA = '/etc/ssl/certs/ca-certificates.crt'
# Mozilla inclusion record: https://bugzilla.mozilla.org/show_bug.cgi?id=1478476
R6_SHA256 = '2cabeafe37d06ca22aba7391c0033d25982952c453647349763a3ab5ad6ccf69'
EXPORT = ('import json, os; names=' + repr(NAMES)
          + '; print(json.dumps({n:os.environ.get(n, "") for n in names}))')


@guarded
def validate_ca(raw):
    """Only public PEM certificates, pinned R6 present, no private keys/extra data."""
    require(isinstance(raw, bytes) and 0 < len(raw) <= 1024 * 1024, 'S3_HOST_CA_INVALID')
    text = raw.decode('ascii')
    pattern = r'-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\s]+?-----END CERTIFICATE-----'
    certs = re.findall(pattern, text)
    require(bool(certs) and not re.sub(pattern, '', text).strip(), 'S3_HOST_CA_INVALID')
    roots = [hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert)).hexdigest() for cert in certs]
    require(R6_SHA256 in roots, 'S3_HOST_CA_R6_MISSING')
    context = ssl.create_default_context(cadata=text)
    require(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname, 'S3_HOST_TLS_REQUIRED')
    return {'certificates': len(certs), 'sha256': hashlib.sha256(raw).hexdigest(),
            'globalsign_r6_sha256': R6_SHA256, 'certificate_verification': True,
            'hostname_verification': True}


@guarded
def prepare_ca(container, destination, *, transport=runtime):
    """Copy PUBLIC trust only; exclusive write, never replace an existing bundle."""
    path = Path(destination)
    _no_links(path)
    raw = transport.docker('exec', container, 'cat', PUBLIC_CA, timeout=30)
    report = validate_ca(raw)
    if path.exists():
        require(path.is_file() and path.stat().st_nlink == 1 and path.read_bytes() == raw,
                'S3_HOST_CA_EXISTS_DIFFERENT')
    else:
        require(path.parent.is_dir(), 'S3_HOST_CA_PARENT_REQUIRED')
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    require(path.read_bytes() == raw, 'S3_HOST_CA_READBACK_FAILED')
    return report


@contextmanager
def process_environment(container, ca_bundle, *, transport=runtime):
    """Whitelist over captured PIPE, never argv/file/console. Restore even on error.

    No promise of secure erasure of immutable Python strings or of protection from
    host administrators, crash dumps, malicious Docker daemons or parallel threads.
    All logging is disabled during the temporary environment's lifetime.
    """
    previous = {n: os.environ.get(n) for n in ENVIRONMENT}
    previous_logging = logging.root.manager.disable
    parameters = {}
    raw = None
    try:
        logging.disable(logging.CRITICAL)
        path = Path(ca_bundle)
        _no_links(path)
        require(path.is_file() and path.stat().st_nlink == 1, 'S3_HOST_CA_INVALID')
        validate_ca(path.read_bytes())  # Before any credential handoff or SDK request.
        try:
            raw = transport.docker('exec', container, '/usr/bin/python3', '-c', EXPORT, timeout=30)
            require(isinstance(raw, bytes) and len(raw) <= 65536, 'S3_HOST_PARAMETERS_INVALID')
            candidate = json.loads(raw)
            require(isinstance(candidate, dict) and set(candidate) == set(NAMES)
                    and all(isinstance(v, str) and v.strip() and '\x00' not in v
                            and '\r' not in v and '\n' not in v for v in candidate.values()),
                    'S3_HOST_PARAMETERS_INVALID')
            parameters = candidate
        except Exception:
            raise runtime.RecoveryError('S3_HOST_PARAMETER_HANDOFF_FAILED') from None
        os.environ.update(parameters)
        os.environ['AWS_CA_BUNDLE'] = str(path.resolve())
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        parameters.clear()
        raw = None
        logging.disable(previous_logging)


def readonly_preflight(container, ca_bundle):
    """Reuse the operator's bounded audit/fences, without a backup/key operation.

    Remove temporary variables BEFORE metadata Docker subprocesses. The SDK holds
    resolved credentials and the host CA path only in its own in-memory session.
    """
    from src.common.s3 import create_s3_client
    from src.recovery.s3_dry_run import audit_source
    from src.recovery.s3_lineage import snapshot_digest
    from src.recovery.s3_metadata import DockerMetadataSource
    from src.recovery.s3_operator import require_live_runtime
    from src.recovery.s3_readonly import S3ReadOnly
    from src.recovery.s3_safety import space_plan
    require_live_runtime()
    previous_logging = logging.root.manager.disable
    client = None
    try:
        logging.disable(logging.CRITICAL)
        with process_environment(container, ca_bundle):
            client = create_s3_client()
            require(client._endpoint.http_session._verify == str(Path(ca_bundle).resolve()),
                    'S3_HOST_TLS_REQUIRED')
            source = S3ReadOnly(client, os.environ['S3_BUCKET'].strip())
        metadata = DockerMetadataSource(runtime.source_container('football-postgres'),
                                        runtime.source_container('football-clickhouse'))
        baseline = metadata.snapshot()
        audit = audit_source(source, baseline)
        require(snapshot_digest(metadata.snapshot()) == snapshot_digest(baseline), 'S3_METADATA_BASELINE_CHANGED')
        return {'status': 'PASS_HOST_READ_ONLY_AUDIT', 'source_check': audit,
                'plan': space_plan(audit['bytes'], audit['objects']),
                'temporary_environment_restored': True,
                'credential_handoff': 'CAPTURED_PIPE_PROCESS_ONLY_FROM_EXISTING_SCHEDULER',
                'live_backup_executed': False, 'recovery_key_created': False,
                'backup_authorization': 'BLOCKED_SEPARATE_KEY_ESCROW_AND_APPROVAL_REQUIRED'}
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            logging.disable(previous_logging)
