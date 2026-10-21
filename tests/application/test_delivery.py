"""Offline production settings and packaging contracts; no infrastructure IO."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured

ROOT = Path(__file__).resolve().parents[2]


class DeliverySettingsTests(unittest.TestCase):
    def settings(self, environment):
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(ROOT / 'application/settings.py'))

    def test_development_keeps_secret_fallback_and_does_not_trust_proxy(self):
        result = self.settings({})
        self.assertFalse(result['DEBUG'])
        self.assertTrue(result['SECRET_KEY'])
        self.assertIsNone(result['SECURE_PROXY_SSL_HEADER'])

    def test_production_requires_runtime_secret(self):
        for value in ('', 'set_me', 'change_me'):
            with self.assertRaises(ImproperlyConfigured):
                self.settings({'API_SERVING_MODE': 'production', 'DJANGO_SECRET_KEY': value})

    def test_production_settings_without_changing_api_contract(self):
        result = self.settings({'API_SERVING_MODE': 'production', 'DJANGO_SECRET_KEY': 'offline-test-only',
                                'API_ALLOWED_HOSTS': 'localhost,football-api-prod'})
        self.assertFalse(result['DEBUG'])
        self.assertEqual(result['SECRET_KEY'], 'offline-test-only')
        self.assertEqual(result['ALLOWED_HOSTS'], ['localhost', 'football-api-prod'])
        self.assertEqual(result['SECURE_PROXY_SSL_HEADER'], ('HTTP_X_FORWARDED_PROTO', 'https'))
        self.assertEqual(result['INSTALLED_APPS'], [])

    def test_gunicorn_is_conservative_and_logs_no_query_or_headers(self):
        config = runpy.run_path(str(ROOT / 'docker/api/gunicorn.conf.py'))
        self.assertEqual(config['workers'], 2)
        self.assertEqual(config['timeout'], 60)
        self.assertEqual(config['bind'], '0.0.0.0:8000')
        self.assertEqual(config['accesslog'], '-')
        self.assertNotIn('%(q)', config['access_log_format'])
        self.assertNotIn('%(r)', config['access_log_format'])


if __name__ == '__main__':
    unittest.main()
