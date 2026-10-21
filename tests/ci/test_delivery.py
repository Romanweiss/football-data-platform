"""Compose/CI production boundary contracts, without reading local secrets."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class DeliveryBoundaryTests(unittest.TestCase):
    def test_private_passes_is_excluded_from_git_and_docker_context(self):
        for filename in ('.gitignore', '.dockerignore'):
            lines = (ROOT / filename).read_text().splitlines()
            self.assertIn('.passes', lines)

    def test_production_opt_in_and_api_internal_with_readonly_identity(self):
        services = yaml.safe_load((ROOT / 'compose.yaml').read_text())['services']
        for name in ('football-web-prod', 'football-api-prod'):
            service = services[name]
            self.assertEqual(service['profiles'], ['app-prod'])
            self.assertEqual(service['build']['target'], 'production')
            self.assertNotIn('volumes', service)
        api = services['football-api-prod']
        self.assertNotIn('ports', api)
        self.assertEqual(api['environment']['CLICKHOUSE_USER'], '${SUPERSET_CLICKHOUSE_USER}')
        self.assertFalse(any('S3' in key or 'POSTGRES' in key for key in api['environment']))
        for name in ('football-web', 'football-api'):
            self.assertEqual(services[name]['build']['target'], 'dev')

    def test_ci_builds_production_targets_without_publication(self):
        workflow = yaml.load((ROOT / '.github/workflows/ci-integration.yml').read_text(), Loader=yaml.BaseLoader)
        job = workflow['jobs']['application-images']
        build = next(step for step in job['steps'] if step.get('uses', '').startswith('docker/build-push-action@'))
        self.assertEqual(build['with']['target'], 'production')
        self.assertEqual(build['with']['push'], 'false')

    def test_frontend_never_receives_server_environment(self):
        dockerfile = (ROOT / 'docker/web/Dockerfile').read_text()
        self.assertNotIn('ARG ', dockerfile)
        runtime = dockerfile.split('AS production')[1]
        self.assertIn('COPY --from=build /app/dist', runtime)
        self.assertNotIn('node_modules', runtime)
        self.assertIn('USER nginx', runtime)

    def test_api_production_image_fails_closed_without_runtime_key(self):
        dockerfile = (ROOT / 'docker/api/Dockerfile').read_text()
        runtime = dockerfile.split('AS production')[1]
        self.assertIn('ENV API_SERVING_MODE=production', runtime)
        self.assertIn('"gunicorn"', runtime)
        self.assertNotIn('runserver', runtime)


if __name__ == '__main__':
    unittest.main()
