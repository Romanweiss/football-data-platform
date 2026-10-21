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
        assert path.parts[:2] != ('data', 'work'), 'Runtime state is tracked'
        assert path.suffix.lower() not in ('.enc', '.dump', '.sqlite', '.key', '.pem', '.p12'), 'Private backup/key artifact is tracked'


def workflow_contract(document):
    assert document['permissions'] == {'contents': 'read'}, 'Workflow permissions must be read-only'
    events = document['on']
    assert set(events) <= {'push', 'pull_request', 'workflow_dispatch'}, 'Unsafe workflow trigger'
    assert 'pull_request' in events and events['push']['branches'] == ['master'], 'Missing normal branch/PR gates'
    assert 'github.workflow' in document['concurrency']['group'] and 'github.ref' in document['concurrency']['group']
    for job in document['jobs'].values():
        assert 1 <= int(job['timeout-minutes']) <= 60, 'Missing/bad timeout'
        assert job['runs-on'] == 'ubuntu-24.04', 'Runner must be intentional'
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
    excluded = {'.env', '.passes', 'keys.txt', 'backups/audit.enc', '.recovery-keys/audit.key'}
    result = subprocess.run(['git', 'check-ignore', *sorted(excluded)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0 and set(result.stdout.splitlines()) == excluded, 'Local secrets/backups must stay ignored'
    docker_exclusions = set((ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines())
    assert {'.env', '.passes', 'keys.txt', 'backups/', '.recovery-keys/'} <= docker_exclusions, 'Private Docker context boundary missing'
    print('Workflow, publication completeness, private-artifact exclusion and tracked-file secret-signature checks passed')


if __name__ == '__main__':
    main()
