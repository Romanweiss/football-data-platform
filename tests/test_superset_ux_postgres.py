"""Offline target-gate tests. No PostgreSQL, Superset, network or secret reads."""
from types import SimpleNamespace
import unittest

from scripts.superset_ux_postgres import require_target, safe_database_error, digest, transact_postgres
from src.analytics.superset_ux import ALLOWED_PATHS, UXConflict


def url(**changes):
    values = dict(host="127.0.0.1", port=5432, database="football_superset_ux4",
                  username="ux4_fixture", password=None, query={}, get_backend_name=lambda: "postgresql")
    values.update(changes)
    return SimpleNamespace(**values)


class PostgresGateTests(unittest.TestCase):
    def test_exact_ephemeral_target_only(self):
        require_target(url())
        for change in ({"host": "football-superset-db"}, {"host": "localhost"},
                       {"database": "superset"}, {"username": "postgres"}, {"port": 5433},
                       {"password": "synthetic-test-only"}, {"query": {"host": "other"}},
                       {"get_backend_name": lambda: "sqlite"}):
            with self.assertRaisesRegex(UXConflict, "ISOLATED_POSTGRES_TARGET_REQUIRED"):
                require_target(url(**change))

    def test_safe_database_error_codes(self):
        for code, expected in (("55P03", "POSTGRES_LOCK_CONFLICT"),
                               ("40001", "POSTGRES_SERIALIZATION_CONFLICT"),
                               ("40P01", "POSTGRES_DEADLOCK_CONFLICT"),
                               (None, "POSTGRES_TRANSACTION_FAILURE")):
            error = SimpleNamespace(orig=SimpleNamespace(pgcode=code))
            self.assertEqual(safe_database_error(error), expected)

    def test_digest_is_deterministic_and_sensitive(self):
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))
        self.assertNotEqual(digest({"a": 1}), digest({"a": 2}))

    def test_unexpected_errors_never_expose_database_messages(self):
        class Broken:
            bundle = {"config-patch.json": [{"path": p, "before": "old", "after": "new"}
                                            for p in sorted(ALLOWED_PATHS)]}

            def begin(self):
                raise RuntimeError("synthetic-sensitive-database-detail")
        with self.assertRaisesRegex(UXConflict, "^POSTGRES_TRANSACTION_FAILURE$"):
            transact_postgres(Broken(), "apply")


if __name__ == "__main__":
    unittest.main()
