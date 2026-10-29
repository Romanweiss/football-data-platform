"""Repository-only checks; never open ignored credentials or print matched values."""
from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]

# A working-tree file is not sufficient: checkout-based CI must receive it too.
PUBLICATION_REQUIRED = frozenset({
    'compose.yaml', 'docker/api/Dockerfile', 'docker/api/gunicorn.conf.py',
    'docker/web/Dockerfile', 'docker/web/nginx.conf', 'application/settings.py',
    'requirements/api.txt', 'frontend/package.json', 'frontend/package-lock.json',
    'frontend/playwright.delivery.config.ts', 'frontend/tests/smoke/delivery.spec.ts',
    'ci/check_delivery.py', 'tests/application/test_delivery.py', 'tests/ci/test_delivery.py',
    'docs/stage8b.md', 'src/recovery/__init__.py', 'src/recovery/archive.py',
    'src/recovery/operations.py', 'src/recovery/runtime.py', 'src/recovery/s3_inventory.py',
    'scripts/backup.py', 'ci/check_recovery.py', 'requirements/recovery.txt',
    'requirements/ci.txt', 'tests/test_recovery.py', 'docs/stage8c.md',
    '.gitignore', '.dockerignore', '.github/workflows/ci-fast.yml',
    '.github/workflows/ci-integration.yml',
    'src/recovery/s3_archive.py', 'src/recovery/s3_storage.py', 'src/recovery/s3_lineage.py',
    'src/recovery/s3_workflow.py', 'src/recovery/s3_readonly.py', 'src/recovery/s3_metadata.py',
    'src/recovery/s3_dry_run.py', 'src/recovery/s3_operator.py', 'src/recovery/s3_safety.py',
    'scripts/check_s3_recovery_dry_run.py', 'scripts/s3_backup.py', 'requirements/recovery-s3.txt',
    'tests/test_s3_archive.py', 'tests/test_s3_workflow.py', 'tests/test_s3_readonly.py',
    'tests/test_s3_operator.py', 'tests/test_s3_windows_acl.py', 'ci/check_s3_recovery.py',
    'docs/stage8c-r2-3a.md', 'docs/stage8c-r2-3b.md', 'docs/stage8c-r2-3c.md',
    'docs/stage8c-r2-3d.md', 'docs/stage8c-r2-3-publication.md',
    'src/recovery/s3_host.py', 'src/recovery/s3_diagnostics.py', 'src/recovery/s3_manual_drill.py',
    'scripts/check_s3_host_readiness.py', 'scripts/show_synthetic_escrow_key.py',
    'scripts/receive_synthetic_escrow_key.py', 'tests/test_s3_host.py',
    'tests/test_s3_diagnostics.py', 'tests/test_s3_escrow.py', 'tests/test_s3_manual_drill.py',
    'docs/stage8c-r2-4a1.md', 'docs/stage8c-r2-4a1-5.md', 'docs/stage8c-r2-4a1-6.md',
    'docs/stage8c-r2-4a1-7.md', 'docs/stage8c-r2-4a1-publication.md',
    'src/recovery/s3_key_escrow.py', 'scripts/show_s3_recovery_key.py',
    'scripts/receive_s3_recovery_key.py', 'tests/test_s3_key_escrow.py',
    'tests/test_s3_key_recovery.py', 'docs/stage8c-r2-4a2-1.md', 'docs/stage8c-r2-4a2-2.md',
    'src/recovery/s3_offline_restore.py', 'scripts/restore_s3_offline.py',
    'tests/test_s3_offline_restore.py', 'docs/stage8c-r2-4a2-4a.md',
    'application/passes.py', 'tests/application/test_passes.py', 'docs/stage9b1.md',
    'frontend/src/components/PassMap.tsx', 'frontend/src/contextLabels.ts',
    'frontend/tests/passes.test.tsx', 'frontend/tests/smoke/pass-map.spec.ts',
    'frontend/playwright.ci.config.ts',
    'application/heatmap.py', 'tests/application/test_heatmap.py',
    'tests/integration/test_clickhouse_heatmap.py', 'tests/ci/test_heatmap.py',
    'frontend/src/components/PressureHeatmap.tsx', 'frontend/tests/heatmap.test.tsx',
    'frontend/src/pressureDensity.ts', 'frontend/tests/density.test.tsx',
    'frontend/tests/smoke/pressure-heatmap.spec.ts', 'docs/stage9b2.md',
    'docs/stage9b1-deployment.md', 'README.ru.md',
    'ci/Dockerfile.dockerignore',
})


def publication_contract(tracked):
    paths = set(filter(None, tracked))
    missing = PUBLICATION_REQUIRED - paths
    assert not missing, 'Required source files missing from Git index: ' + ', '.join(sorted(missing))
    for name in paths:
        path = Path(name)
        assert path.name not in ('.env', '.passes', 'keys.txt'), 'Credential file is tracked'
        assert not ({'backups', '.recovery-keys', 'node_modules', '__pycache__', '.venv',
                     'test-results', 'playwright-report'} & set(path.parts)), 'Private/generated directory is tracked'
        assert not ({'tmp', '.tmp'} & set(path.parts)), 'Temporary state is tracked'
        assert not ({'footballrecoveryvault', 'footballplatformbackups'}
                    & {part.casefold() for part in path.parts}), 'Operator recovery state is tracked'
        assert path.parts[0] != 'data' or name == 'data/samples/sample_match.json', 'Non-synthetic data is tracked'
        assert path.suffix.lower() not in ('.enc', '.dump', '.backup', '.sqlite', '.sqlite3', '.db',
                                           '.key', '.pem', '.p12', '.pfx', '.crt', '.cer'), 'Private backup/key/CA artifact is tracked'


def workflow_contract(document):
    assert document['permissions'] == {'contents': 'read'}, 'Workflow permissions must be read-only'
    events = document['on']
    assert set(events) <= {'push', 'pull_request', 'workflow_dispatch'}, 'Unsafe workflow trigger'
    assert 'pull_request' in events and events['push']['branches'] == ['master'], 'Missing normal branch/PR gates'
    assert 'github.workflow' in document['concurrency']['group'] and 'github.ref' in document['concurrency']['group']
    for name, job in document['jobs'].items():
        assert 1 <= int(job['timeout-minutes']) <= 60, 'Missing/bad timeout'
        assert job['runs-on'] == ('windows-2022' if name == 's3-recovery-windows' else 'ubuntu-24.04'), 'Runner must be intentional'
        for step in job['steps']:
            if 'uses' in step:
                assert re.fullmatch(r'[\w-]+/[\w-]+@(v\d+|[a-f0-9]{40})', step['uses']), 'Unpinned action'
            text = str(step)
            assert 'pull_request_target' not in text and 'secrets.' not in text, 'CI must need no project secrets'
            assert step.get('with', {}).get('push', 'false') == 'false', 'Image publication forbidden'


def secret_findings(text):
    # Deliberately high-confidence signatures. Not an entropy scanner or full git-history audit.
    patterns = {
        'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'aws-access-key': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
        'github-token': r'\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{70,})\b',
    }
    return [(number, kind) for number, line in enumerate(text.splitlines(), 1)
            for kind, pattern in patterns.items() if re.search(pattern, line)]


def main():
    for path in sorted((ROOT / '.github/workflows').glob('*.yml')):
        workflow_contract(yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader))
    compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
    template = (ROOT / '.env.example').read_text(encoding='utf-8')
    names = set(re.findall(r'^([A-Z][A-Z0-9_]*)=', template, re.M))
    required = set(re.findall(r'(?<!\$)\$\{([A-Z][A-Z0-9_]*)\}', compose))
    assert required <= names, 'Required Compose variable names missing in .env.example'
    # Only tracked paths: ignored .env/keys.txt are not read, even for scanning.
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    # Reject private paths before opening any tracked file, including accidental staging.
    publication_contract(tracked)
    findings = []
    for name in filter(None, tracked):
        path = Path(name)
        assert path.name not in ('.env', '.passes', 'keys.txt'), 'Credential file is tracked'
        if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.ico', '.woff2', '.parquet'):
            continue
        content = (ROOT / path).read_text(encoding='utf-8', errors='replace')
        findings.extend((name, line, kind) for line, kind in secret_findings(content))
    for path, line, kind in findings:
        print(f'{path}:{line}: suspected {kind}; value suppressed')
    assert not findings, 'Review suspected committed credential signatures privately'
    excluded = {'.env', '.passes', 'keys.txt', 'backups/audit.enc', '.recovery-keys/audit.key',
                'outside-backups/audit.enc', 'outside-backups/audit.key', 'restore.dump',
                'restore.sqlite3', 'runtime.db', 'data/work/runtime.json', '.tmp/state.json',
                'host-ca.crt', 'outside-certs/host-ca.cer', '.venv/s3-recovery/certs/host-ca.pem'}
    result = subprocess.run(['git', 'check-ignore', *sorted(excluded)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0 and set(result.stdout.splitlines()) == excluded, 'Local secrets/backups must stay ignored'
    docker_exclusions = set((ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines())
    assert {'.env', '.passes', 'keys.txt', 'backups/', '.recovery-keys/'} <= docker_exclusions, 'Private Docker context boundary missing'
    assert {'*.enc', '*.key', '*.pem', '*.dump', '*.sqlite3', '*.db', 'tmp/', '.tmp/',
            'data/*', '!data/samples/', 'data/samples/*', '!data/samples/sample_match.json'} <= docker_exclusions, 'Runtime/payload Docker context boundary missing'
    assert {'*.crt', '*.cer', '**/*.crt', '**/*.cer',
            '**/*.enc', '**/*.key', '**/*.pem', '**/*.dump', '**/*.sqlite3', '**/*.db',
            '**/.env', '**/.passes', '**/keys.txt'} <= docker_exclusions, 'Nested Docker credential/artifact boundary missing'
    sample = subprocess.run(['git', 'check-ignore', 'data/samples/sample_match.json'], cwd=ROOT, capture_output=True)
    assert sample.returncode == 1, 'The committed synthetic sample must remain publishable'
    print('Workflow, publication completeness, private-artifact exclusion and tracked-file secret-signature checks passed')


if __name__ == '__main__':
    main()
