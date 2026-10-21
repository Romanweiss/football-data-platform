"""Read-only R2.3-C check using existing containers; no env files or secret argv."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recovery.runtime import RecoveryError, docker, encoded, require, source_container
from src.recovery.s3_lineage import snapshot_digest
from src.recovery.s3_metadata import DockerMetadataSource

# Current audited source is installed IN MEMORY in the existing credential-owning
# runtime. No image rebuild, file copy, secret transfer or production CLI change.
REMOTE = r'''
import importlib.abc, importlib.util, json, os, sys
# The existing image separates SDK (/usr/bin Python) and Airflow crypto dependencies.
# Reuse the installed, same-interpreter-version venv libraries for this process only.
sys.path.append('/opt/airflow-venv/lib/python' + str(sys.version_info.major) + '.' +
                str(sys.version_info.minor) + '/site-packages')
payload = json.load(sys.stdin)
class Sources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in payload['modules']:
            return importlib.util.spec_from_loader(fullname, self,
                is_package=payload['modules'][fullname]['package'])
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        entry = payload['modules'][module.__name__]
        module.__file__ = '/in-memory-audit/' + module.__name__.replace('.', '/') + '.py'
        exec(compile(entry['source'], module.__file__, 'exec'), module.__dict__)
sys.meta_path.insert(0, Sources())
stage = 'imports'
try:
    from src.common.s3 import create_s3_client
    from src.recovery.runtime import RecoveryError
    from src.recovery.s3_readonly import S3ReadOnly
    from src.recovery.s3_dry_run import audit_source
    stage = 'sdk_configuration'
    adapter = S3ReadOnly(create_s3_client(), os.environ.get('S3_BUCKET', ''))
    stage = 'source_audit'
    result = audit_source(adapter, payload['snapshot'])
    print(json.dumps(result, sort_keys=True))
except Exception as exc:
    # Never print SDK/provider messages, metadata values, environment or payloads.
    code = str(exc) if 'RecoveryError' in globals() and isinstance(exc, RecoveryError) else 'AUDIT_FAILED_' + stage + '_' + type(exc).__name__
    print(json.dumps({'error': code}))
'''


def modules():
    """Only repo Python sources, never private/runtime files. Import is lazy."""
    result = {}
    for path in sorted((ROOT / 'src').rglob('*.py')):
        parts = path.relative_to(ROOT).with_suffix('').parts
        package = parts[-1] == '__init__'
        name = '.'.join(parts[:-1] if package else parts)
        result[name] = {'source': path.read_text(encoding='utf-8'), 'package': package}
    return result


def main():
    metadata = DockerMetadataSource(source_container('football-postgres'), source_container('football-clickhouse'))
    baseline = metadata.snapshot()
    baseline_hash = snapshot_digest(baseline)
    # Only source code and detached catalog DTOs enter the runtime; credentials never leave it.
    raw = docker('exec', '-i', '-e', 'PYTHONDONTWRITEBYTECODE=1', source_container('football-airflow-scheduler'),
                 '/usr/bin/python3', '-B', '-c', REMOTE,
                 data=encoded({'modules': modules(), 'snapshot': baseline}), timeout=900)
    report = json.loads(raw)
    require('error' not in report, report.get('error', 'S3_DRY_RUN_FAILED'))
    require(snapshot_digest(metadata.snapshot()) == baseline_hash, 'S3_METADATA_BASELINE_CHANGED')
    report['metadata_fence'] = 'PASS'
    report['metadata_sha256'] = baseline_hash
    report['catalog_counts'] = {k: len(v) for k, v in baseline['catalog'].items()}
    report['serving_tables'] = len(baseline['serving'])
    report['serving_rows'] = sum(int(g['rows']) for t in baseline['serving'].values() for g in t['groups'])
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, RecoveryError) else 'S3_DRY_RUN_FAILED'}))
        sys.exit(1)
