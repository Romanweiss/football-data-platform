"""Repository-only checks; never open ignored credentials or print matched values."""
from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]


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
    findings = []
    for name in filter(None, tracked):
        path = Path(name)
        assert path.name not in ('.env', 'keys.txt'), 'Credential file is tracked'
        if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.ico', '.woff2', '.parquet'):
            continue
        content = (ROOT / path).read_text(encoding='utf-8', errors='replace')
        findings.extend((name, line, kind) for line, kind in secret_findings(content))
    for path, line, kind in findings:
        print(f'{path}:{line}: suspected {kind}; value suppressed')
    assert not findings, 'Review suspected committed credential signatures privately'
    result = subprocess.run(['git', 'check-ignore', '.env', 'keys.txt'], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0 and set(result.stdout.splitlines()) == {'.env', 'keys.txt'}, 'Local secrets must stay ignored'
    print('Workflow, environment-template and tracked-file secret-signature checks passed')


if __name__ == '__main__':
    main()
