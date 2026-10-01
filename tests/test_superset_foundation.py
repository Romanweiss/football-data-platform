"""Stage 4A configuration/init contracts without importing Superset or service IO."""

import io
import os
import re
import runpy
import subprocess
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "infrastructure/superset/superset_config.py"
INIT = ROOT / "infrastructure/superset/init_superset.py"
ENV = {"SUPERSET_SECRET_KEY": "synthetic-key-for-offline-testing-only-12345",
       "SUPERSET_DB_NAME": "superset", "SUPERSET_DB_USER": "user:@/?#%",
       "SUPERSET_DB_PASSWORD": "synthetic:p@ss/?#%", "SUPERSET_DB_HOST": "football-superset-db"}


class SupersetConfigTests(unittest.TestCase):
    def config(self, env):
        with patch.dict(os.environ, env, clear=True):
            return runpy.run_path(str(CONFIG))

    def test_safe_metadata_uri_and_synchronous_flags(self):
        config = self.config(ENV)
        uri = urlsplit(config["SQLALCHEMY_DATABASE_URI"])
        self.assertEqual(uri.scheme, "postgresql+psycopg2")
        self.assertEqual(unquote(uri.username), ENV["SUPERSET_DB_USER"])
        self.assertEqual(unquote(uri.password), ENV["SUPERSET_DB_PASSWORD"])
        self.assertEqual((uri.hostname, uri.port, uri.path), ("football-superset-db", 5432, "/superset"))
        self.assertFalse(config["FEATURE_FLAGS"]["GLOBAL_ASYNC_QUERIES"])
        self.assertFalse(config["FEATURE_FLAGS"]["ALERT_REPORTS"])
        self.assertTrue(config["WTF_CSRF_ENABLED"])

    def test_required_settings_fail_without_secret_values_or_defaults(self):
        for name in ENV:
            for value in ("", " "):
                with self.subTest(name=name), self.assertRaises(ValueError) as error:
                    self.config({**ENV, name: value})
                for secret in ENV.values():
                    if secret.startswith("synthetic"):
                        self.assertNotIn(secret, str(error.exception))
        for changes in ({"SUPERSET_SECRET_KEY": "change_me"}, {"SUPERSET_DB_NAME": "football_metadata"},
                        {"SUPERSET_DB_HOST": "football-postgres"}):
            with self.assertRaises(ValueError):
                self.config({**ENV, **changes})

    def test_only_placeholders_in_env_example_and_env_excluded(self):
        values = dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text().splitlines() if "=" in line and not line.startswith("#"))
        for key in ("SUPERSET_SECRET_KEY", "SUPERSET_DB_PASSWORD", "SUPERSET_ADMIN_PASSWORD", "SUPERSET_CLICKHOUSE_PASSWORD"):
            self.assertIn(values[key], ("", "set_me"))
        self.assertEqual(values["SUPERSET_CLICKHOUSE_USER"], "superset_reader")
        self.assertIn(".env", (ROOT / ".gitignore").read_text().splitlines())
        self.assertIn(".env", (ROOT / ".dockerignore").read_text().splitlines())

    def test_pinned_image_driver_and_nonroot_user(self):
        dockerfile = (ROOT / "docker/superset/Dockerfile").read_text()
        requirements = (ROOT / "requirements/superset.txt").read_text()
        pin = next(line for line in (ROOT / "requirements/tools.txt").read_text().splitlines() if line.startswith("clickhouse-connect=="))
        self.assertIn(pin, requirements)
        self.assertIn("psycopg2-binary==2.9.6", requirements)
        self.assertRegex(dockerfile, r"\AFROM apache/superset:6\.0\.0@sha256:[0-9a-f]{64}\n")
        self.assertTrue(dockerfile.rstrip().endswith("USER superset"))
        self.assertIn("--constraint /app/requirements/base.txt", dockerfile)
        self.assertNotIn("clickhouse-sqlalchemy", requirements)
        self.assertNotIn("COPY . ", dockerfile)


class SupersetInitTests(unittest.TestCase):
    def setUp(self):
        self.module = runpy.run_path(str(INIT))
        self.settings = {"SUPERSET_ADMIN_USERNAME": "operator", "SUPERSET_ADMIN_PASSWORD": "synthetic-secret", "SUPERSET_ADMIN_EMAIL": "test@example.invalid"}

    def test_create_once_existing_does_not_reset_password(self):
        manager = MagicMock()
        manager.find_user.return_value = None
        self.assertEqual(self.module["ensure_admin"](manager, self.settings), "CREATED")
        self.assertEqual(manager.add_user.call_args.kwargs["password"], "synthetic-secret")
        manager.find_user.return_value = SimpleNamespace(active=True, roles=[SimpleNamespace(name="Admin")])
        self.assertEqual(self.module["ensure_admin"](manager, self.settings), "EXISTS")
        manager.add_user.assert_called_once()

    def test_existing_nonadmin_or_inactive_and_failed_creation_are_errors(self):
        manager = MagicMock()
        for user in (SimpleNamespace(active=True, roles=[]), SimpleNamespace(active=False, roles=[SimpleNamespace(name="Admin")])):
            manager.find_user.return_value = user
            with self.assertRaises(RuntimeError):
                self.module["ensure_admin"](manager, self.settings)
        manager.add_user.assert_not_called()
        manager.find_user.return_value = None
        manager.add_user.return_value = False
        with self.assertRaises(RuntimeError):
            self.module["ensure_admin"](manager, self.settings)

    def test_no_missing_or_admin_admin_credentials(self):
        for env in ({}, {**self.settings, "SUPERSET_ADMIN_PASSWORD": ""}, {**self.settings, "SUPERSET_ADMIN_PASSWORD": "operator"}):
            with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                self.module["admin_settings"]()

    def test_subprocess_failures_are_not_hidden_or_logged_raw(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["superset"], output=b"synthetic-secret")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                self.module["run_command"]("db", "upgrade")
            self.assertEqual(run.call_args.args[0], ["superset", "db", "upgrade"])
            self.assertTrue(run.call_args.kwargs["check"])
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(self.module["main"](), 1)
        self.assertIn("stage=configuration", output.getvalue())
        self.assertNotIn("synthetic-secret", output.getvalue())
        self.assertNotIn("|| true", INIT.read_text())


class SupersetComposeAndAccessTests(unittest.TestCase):
    def test_scoped_select_only_and_readonly_profile(self):
        root = ET.parse(ROOT / "infrastructure/clickhouse/users.d/20_superset_reader.xml").getroot()
        user = root.find("users/superset_reader")
        self.assertEqual(user.find("password").attrib, {"from_env": "SUPERSET_CLICKHOUSE_PASSWORD"})
        self.assertFalse(user.findtext("password"))
        self.assertEqual([item.text for item in user.findall("grants/query")], ["GRANT SELECT ON football.*"])
        self.assertEqual(root.findtext("profiles/superset_readonly/readonly"), "1")
        self.assertEqual(user.findtext("profile"), "superset_readonly")
        self.assertIsNone(user.find("access_management"))
        self.assertIsNone(user.find("named_collection_control"))

    def test_compose_isolated_db_health_dependencies_and_secret_boundaries(self):
        source = (ROOT / "compose.yaml").read_text().split("\nnetworks:")[0]
        services = dict(re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", source, re.M | re.S))
        db, app, init = (services[name] for name in ("football-superset-db", "football-superset", "football-superset-init"))
        self.assertIn("postgres:17.6-alpine3.22", db)
        self.assertNotIn("ports:", db)
        self.assertIn("football_superset_db_data:/var/lib/postgresql/data", db)
        self.assertIn("pg_isready", db)
        self.assertIn('127.0.0.1:${SUPERSET_HOST_PORT:-18088}:8088', app)
        self.assertIn("http://localhost:8088/health", app)
        self.assertIn("urllib.request", app)
        self.assertIn("service_completed_successfully", app)
        self.assertIn('restart: "no"', init)
        for service in (app, init):
            self.assertIn("service_healthy", service)
            self.assertIn("SUPERSET_DB_HOST: football-superset-db", service)
            for forbidden in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "${CLICKHOUSE_PASSWORD}", "${POSTGRES_PASSWORD}"):
                self.assertNotIn(forbidden, service)
            self.assertNotRegex(service, r"(?m)^\s+CLICKHOUSE_PASSWORD:")
        self.assertNotIn("SUPERSET_ADMIN_PASSWORD", app)
        ch = services["football-clickhouse"]
        self.assertIn("${SUPERSET_CLICKHOUSE_PASSWORD:?", ch)
        self.assertIn("10_named_collection_access.xml:ro", ch)
        self.assertIn("20_superset_reader.xml:ro", ch)
        self.assertNotIn("users.d:/etc/clickhouse-server/users.d", ch)


if __name__ == "__main__":
    unittest.main()
