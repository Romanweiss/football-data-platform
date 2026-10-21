"""Offline image/proxy acceptance. Isolated containers never join platform networks.

Uses only synthetic configuration; never opens .env or accesses platform data.
Run on a Docker host with Python 3.10+ after building both production images.
"""
import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT).strip()


def audit(image, kind):
    user = docker('image', 'inspect', '--format', '{{.Config.User}}', image)
    assert user not in ('', '0', 'root'), 'Runtime must be non-root'
    if kind == 'web':
        docker('run', '--rm', '--network', 'none', image, '-t')
        docker('run', '--rm', '--network', 'none', '--entrypoint', 'sh', image, '-ec',
               '! command -v node; ! command -v npm; '
               'test ! -d /app; test -f /usr/share/nginx/html/index.html; '
               'test -z "$(find /usr/share/nginx/html /etc/nginx -name .env -o -name .passes -o -name keys.txt '
               '-o -name .git -o -name node_modules -o -name __pycache__ -o -name .pytest_cache)"')
    else:
        docker('run', '--rm', '--network', 'none', '--entrypoint', 'python', image, '-c',
               "from pathlib import Path; import os; assert os.getuid() != 0; "
               "names={'.env','.passes','keys.txt','.git','data','tests','node_modules','__pycache__','.pytest_cache'}; "
               "assert not any(p.name in names or p.suffix == '.pyc' for p in Path('/app').rglob('*'))")
        docker('run', '--rm', '--network', 'none', '-e', 'API_SERVING_MODE=production',
               '-e', 'DJANGO_SECRET_KEY=offline-delivery-fixture-only', image,
               'gunicorn', '--check-config', '--config', 'gunicorn.conf.py', 'application.wsgi:application')
    print(f'{kind}: non-root, configuration and shipped-content audit passed')


def get(base, path, headers=None):
    try:
        response = urllib.request.urlopen(urllib.request.Request(base + path, headers=headers or {}), timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, dict(response.headers), response.read()


def wait_for(check, timeout=40):
    deadline = time.monotonic() + timeout
    while True:
        try:
            if check():
                return
        except (OSError, AssertionError):
            pass
        if time.monotonic() >= deadline:
            raise AssertionError('Offline delivery readiness timeout')
        time.sleep(0.25)


def check_proxy(api_image, web_image):
    # No platform mounts, credentials or real datasets. A dedicated bridge is
    # needed for a loopback-published port on Docker Desktop; all test upstream
    # requests target this network or loopback, never the platform/Internet.
    token = uuid.uuid4().hex[:12]
    network, api, web = [f'football-delivery-{token}-{part}' for part in ('net', 'api', 'web')]
    fixture = '''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status = int(urlsplit(self.path).path.rsplit('/', 1)[-1])
        body = json.dumps({'path': self.path, 'host': self.headers['Host'],
            'forwarded_for': self.headers['X-Forwarded-For'],
            'forwarded_proto': self.headers['X-Forwarded-Proto']}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
'''
    created = []
    docker('network', 'create', network)
    try:
        docker('run', '-d', '--name', api, '--network', network, '--network-alias', 'football-api-prod',
               '--entrypoint', 'python', api_image, '-c', fixture)
        created.append(api)
        docker('run', '-d', '--name', web, '--network', network, '-p', '127.0.0.1::8080', web_image)
        created.append(web)
        base = 'http://' + docker('port', web, '8080/tcp')
        wait_for(lambda: get(base, '/api/probe/200')[0] == 200)
        for status in (200, 400, 404, 503, 500):
            path = f'/api/probe/{status}?team_id=779&team_id=771'
            actual, headers, body = get(base, path)
            assert actual == status
            assert headers['Content-Type'] == 'application/json'
            response = json.loads(body)
            assert response['path'] == path, 'URI/query was changed'
            assert response['host'] == base.removeprefix('http://')
            assert response['forwarded_proto'] == 'http'
            assert response['forwarded_for']
        for path in ('/', '/competitions/43/seasons/106/matches/3869685',
                     '/competitions/9/seasons/281/matches/1'):
            status, headers, body = get(base, path)
            assert status == 200 and b'<div id="root">' in body
            assert headers['X-Content-Type-Options'] == 'nosniff'
            assert headers['X-Frame-Options'] == 'DENY'
            assert 'no-cache' in headers['Cache-Control']
        assert get(base, '/assets/missing.js')[0] == 404
        html = get(base, '/')[2].decode()
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
        assert len(assets) >= 2
        for asset in assets:
            status, headers, body = get(base, asset, {'Accept-Encoding': 'gzip'})
            assert status == 200 and body
            assert 'max-age=31536000' in headers['Cache-Control']
            assert headers['Content-Encoding'] == 'gzip'
        docker('rm', '-f', api)  # Only the uniquely named synthetic fixture.
        created.remove(api)
        wait_for(lambda: get(base, '/api/probe/200?diagnostic_token=synthetic-canary')[0] == 502)
        assert get(base, '/')[0] == 200
        # Actual Gunicorn/Django, but an unreachable synthetic CH endpoint.
        docker('run', '-d', '--name', api, '--network', network, '--network-alias', 'football-api-prod',
               '-e', 'API_SERVING_MODE=production', '-e', 'DJANGO_SECRET_KEY=offline-delivery-fixture-only',
               '-e', 'CLICKHOUSE_HOST=127.0.0.1', '-e', 'CLICKHOUSE_HTTP_PORT=1',
               '-e', 'CLICKHOUSE_DB=offline', '-e', 'CLICKHOUSE_USER=offline', '-e', 'CLICKHOUSE_PASSWORD=offline',
               api_image)
        created.append(api)
        wait_for(lambda: get(base, '/api/v1/health')[0] == 200)
        status, headers, body = get(base, '/api/v1/health/clickhouse')
        assert status == 503 and json.loads(body)['error']['code'] == 'clickhouse_unavailable'
        assert headers['Content-Type'] == 'application/json'
        assert get(base, '/')[0] == 200
        logs = docker('logs', api) + docker('logs', web)
        assert 'offline-delivery-fixture-only' not in logs
        assert 'team_id=' not in logs, 'Query values leaked into access logs'
        assert 'synthetic-canary' not in logs, 'Failed upstream leaked request query into logs'
        print('Proxy: GET/query/Host/forwarded headers, 400/404/503/500, SPA and asset caching passed')
        print('Failures: missing API -> 502; actual Django with unreachable CH -> safe JSON 503; static remains 200')
        print('API DNS recreation and bounded safe access logs passed')
    finally:
        for name in reversed(created):
            subprocess.run(['docker', 'rm', '-f', name], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'network', 'rm', network], check=True, stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-image', default='football-api:8b')
    parser.add_argument('--web-image', default='football-web:8b')
    parser.add_argument('--audit-image')
    parser.add_argument('--kind', choices=('api', 'web'))
    args = parser.parse_args()
    if args.audit_image:
        if not args.kind:
            parser.error('--audit-image requires --kind')
        audit(args.audit_image, args.kind)
        return
    audit(args.api_image, 'api')
    audit(args.web_image, 'web')
    check_proxy(args.api_image, args.web_image)


if __name__ == '__main__':
    main()
