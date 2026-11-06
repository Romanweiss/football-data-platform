"""Explicit synthetic PostgreSQL contracts, only in an isolated Superset 6 image.

Requires a fresh ephemeral DB at the fixed loopback-only test target. No live
configuration/credentials, migrations, analytical connections or HTTP requests.
Database schema/fixtures are created; this is NOT a read-only or production CLI.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.machinery
import io
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def isolated_app():
    # Never fall through to the image's live-specific superset_config module.
    os.environ.pop("SUPERSET_CONFIG_PATH", None)
    os.environ.pop("SUPERSET_CONFIG", None)
    empty = types.ModuleType("superset_config")
    empty.__spec__ = importlib.machinery.ModuleSpec("superset_config", loader=None)
    empty.__file__ = "<isolated-no-live-config>"
    sys.modules["superset_config"] = empty
    import superset.config as defaults
    from superset.initialization import SupersetAppInitializer

    class Initializer(SupersetAppInitializer):
        def configure_fab(self):
            super().configure_fab()
            from superset import db
            from superset.models.core import Database
            from superset.models.slice import Slice
            from superset.models.dashboard import Dashboard
            from superset.connectors.sqla.models import SqlaTable, TableColumn, SqlMetric
            from scripts.superset_ux_postgres import require_target
            require_target(db.engine.url)
            metadata = SqlaTable.__table__.metadata
            wanted = {m.__table__ for m in (SqlaTable, TableColumn, SqlMetric, Database, Slice, Dashboard)}
            wanted.update(t for n, t in metadata.tables.items() if n in
                          ("slice_user", "sqlatable_user", "dashboard_user", "dashboard_roles", "dashboard_slices"))
            pending = list(wanted)
            while pending:
                for foreign in pending.pop().foreign_keys:
                    target = foreign.column.table
                    if target not in wanted:
                        wanted.add(target)
                        pending.append(target)
            # Only fixture dependencies, not SQL Lab's unrelated migration-managed schema.
            metadata.create_all(db.engine, tables=list(wanted))

    config = types.ModuleType("ux4_config")
    config.__dict__.update({k: v for k, v in vars(defaults).items() if k.isupper()})
    config.SECRET_KEY = secrets.token_hex(48)
    config.SQLALCHEMY_DATABASE_URI = "postgresql+psycopg2://ux4_fixture@127.0.0.1:5432/football_superset_ux4"
    config.SQLALCHEMY_ENGINE_OPTIONS = {}
    config.TALISMAN_ENABLED = False
    config.FAB_UPDATE_PERMS = False
    config.CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache"}
    config.DATA_CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache"}
    config.APP_INITIALIZER = Initializer
    sys.modules["ux4_config"] = config
    from superset.app import create_app, SupersetApp
    with patch.object(SupersetApp, "sync_config_to_db", lambda self: None):
        return create_app("ux4_config")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-ephemeral-postgres", action="store_true", required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    from src.analytics.superset_ux import UX3_R2_HASHES, load_bundle
    # Bound and authenticate inputs before any database bootstrap/write.
    raw = {}
    for name in UX3_R2_HASHES:
        path = args.bundle_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("BUNDLE_INPUT")
        with path.open("rb") as stream:
            raw[name] = stream.read(2 * 1024 * 1024 + 1)
    load_bundle(raw, "ux3-r2")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        app = isolated_app()
        sys.path.insert(0, str(ROOT / "tests/integration"))
        from superset_ux_postgres_contracts import run_contracts
        with app.app_context():
            result = run_contracts(app, raw)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No SQLAlchemy URLs, SQL statements, parameters, traceback or config values.
        print(json.dumps({"status": "FAIL", "class": type(error).__name__, "code": "ISOLATED_CONTRACT_FAILURE"}))
        raise SystemExit(1) from None
