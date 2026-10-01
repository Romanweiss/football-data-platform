"""Run inside the built image with --network none. Never create the Superset app."""

import importlib.metadata
import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


class SupersetImageTests(unittest.TestCase):
    def test_pins_and_installed_database_dialects(self):
        for name, version in (("apache-superset", "6.0.0"), ("clickhouse-connect", "0.15.0"), ("psycopg2-binary", "2.9.6")):
            self.assertEqual(importlib.metadata.version(name), version)
        for uri, dialect in (("clickhousedb://synthetic:synthetic@football-clickhouse:8123/football", "clickhousedb"),
                             ("postgresql+psycopg2://synthetic:synthetic@football-superset-db:5432/superset", "postgresql")):
            # Engine construction imports the dialect/DBAPI but does not connect.
            engine = create_engine(uri)
            self.assertEqual(engine.dialect.name, dialect)
            engine.dispose()

    def test_real_sqlalchemy_uri_parsing_and_nonroot(self):
        self.assertNotEqual(os.getuid(), 0)
        env = {"SUPERSET_SECRET_KEY": "offline-synthetic-secret-never-for-live-use",
               "SUPERSET_DB_NAME": "superset", "SUPERSET_DB_USER": "special:user@", "SUPERSET_DB_PASSWORD": "synthetic:p@ss/?#%",
               "SUPERSET_DB_HOST": "football-superset-db"}
        path = Path("/app/pythonpath/superset_config.py")
        with patch.dict(os.environ, env, clear=True):
            config = runpy.run_path(str(path))
        uri = make_url(config["SQLALCHEMY_DATABASE_URI"])
        self.assertEqual(uri.username, env["SUPERSET_DB_USER"])
        self.assertEqual(uri.password, env["SUPERSET_DB_PASSWORD"])
        self.assertEqual(uri.database, "superset")


if __name__ == "__main__":
    unittest.main(verbosity=2)
