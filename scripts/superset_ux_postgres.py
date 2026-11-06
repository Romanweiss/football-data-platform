"""UX-4 isolated PostgreSQL adapter. NOT a production writer or live-apply CLI.

No environment discovery, connection creation, credential loading or migrations.
Only the reviewed ux3-r2 bundle and a caller-supplied expected state are accepted.
"""
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from uuid import UUID

from scripts.superset_ux_metadata import IsolatedMetadataStore, MODEL_FIELDS
from src.analytics.superset_ux import ALLOWED_PATHS, UXConflict, cas_value, check, load_bundle, transact

TARGET_DATABASE = "football_superset_ux4"
TARGET_USER = "ux4_fixture"
TARGET_MARKER = "ux4-isolated-postgresql-metadata-v1"
GUARD_TABLE = "ux4_target_guard"
# Fixed identifiers, never derived from CLI, SQL input or an external manifest.
RELATION_TABLES = frozenset({
    "slice_user", "sqlatable_user", "dashboard_user", "dashboard_roles", "dashboard_slices",
    "sql_metrics", "ab_role", "ab_user_role", "ab_permission_view_role",
    "ab_permission_view", "ab_permission", "ab_view_menu",
})


def digest(value):
    def encode(obj):
        if isinstance(obj, (date, datetime, Decimal, UUID)):
            return str(obj)
        if isinstance(obj, bytes):
            return obj.hex()
        raise UXConflict("STATE_TYPE")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=encode).encode()).hexdigest()


def require_target(url):
    check(url.get_backend_name() == "postgresql" and url.host == "127.0.0.1"
          and url.port == 5432 and url.database == TARGET_DATABASE
          and url.username == TARGET_USER and url.password is None and not url.query,
          "ISOLATED_POSTGRES_TARGET_REQUIRED")


def safe_database_error(error):
    code = getattr(getattr(error, "orig", None), "pgcode", None)
    return {"55P03": "POSTGRES_LOCK_CONFLICT", "40001": "POSTGRES_SERIALIZATION_CONFLICT",
            "40P01": "POSTGRES_DEADLOCK_CONFLICT"}.get(code, "POSTGRES_TRANSACTION_FAILURE")


class IsolatedPostgresMetadataStore(IsolatedMetadataStore):
    def __init__(self, session, Chart, Dataset, Dashboard, Column, raw_bundle, expected_fingerprint):
        bundle = load_bundle(raw_bundle, "ux3-r2")
        check(type(expected_fingerprint) is str and len(expected_fingerprint) == 64
              and all(c in "0123456789abcdef" for c in expected_fingerprint), "EXPECTED_FINGERPRINT_REQUIRED")
        require_target(session.get_bind().url)
        super().__init__(session, Chart, Dataset, Dashboard, Column, bundle)
        self.bundle = bundle
        self.expected_fingerprint = expected_fingerprint

    def object(self, path):
        check(path in ALLOWED_PATHS, "FIELD_NOT_ALLOWED")
        return super().object(path)

    def relation_names(self):
        from sqlalchemy import inspect
        names = set(inspect(self.session.connection()).get_table_names(schema="public"))
        required = {"ab_role", "ab_user_role", "ab_permission_view_role", "slice_user",
                    "sqlatable_user", "dashboard_user", "dashboard_slices", "sql_metrics"}
        check(required <= names, "METADATA_SCHEMA_REQUIRED")
        return sorted(names & RELATION_TABLES)

    def begin(self):
        from sqlalchemy import select, text
        require_target(self.session.get_bind().url)
        check(not self.session.in_transaction(), "EXISTING_TRANSACTION")
        try:
            conn = self.session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
            conn.execute(text("SET LOCAL lock_timeout = '2s'"))
            conn.execute(text("SET LOCAL statement_timeout = '15s'"))
            conn.execute(text("SET LOCAL search_path = public"))
            check(conn.execute(text("SELECT marker FROM public.ux4_target_guard WHERE id = 1 FOR SHARE")).scalar()
                  == TARGET_MARKER, "ISOLATED_POSTGRES_MARKER_REQUIRED")
            # Association/RBAC inserts must not race our protected-state check.
            # These names come only from the fixed schema allowlist above.
            for name in self.relation_names():
                conn.execute(text('LOCK TABLE public."' + name + '" IN SHARE ROW EXCLUSIVE MODE'))
            self.session.expire_all()  # Never CAS against an earlier identity-map value.
            for model in [*self.models.values(), self.Column]:
                # Superset model defaults include DISTINCT/eager relationship joins.
                # Lock base-table rows with Core; PostgreSQL forbids FOR UPDATE on DISTINCT.
                identifier = model.__table__.c.id
                conn.execute(select(identifier).order_by(identifier).with_for_update()).all()
            check(self.fingerprint() == self.expected_fingerprint, "METADATA_FINGERPRINT_CONFLICT")
        except Exception:
            self.session.rollback()  # Only the transaction started above.
            raise

    def protected(self):
        from sqlalchemy import inspect, text
        result = {"identity": super().protected(), "objects": {}, "relations": {}}
        for kind, model in self.models.items():
            for obj in self.session.query(model).order_by(model.id):
                owned = {attribute for field, attribute in MODEL_FIELDS[kind].items()
                         if f"/{kind}/{obj.id}/{field}" in ALLOWED_PATHS} - {"columns"}
                # Superset's audit timestamp changes on ORM updates, not a user field.
                result["objects"][f"{kind}/{obj.id}"] = {
                    c.key: getattr(obj, c.key) for c in inspect(model).columns
                    if c.key not in owned and c.key != "changed_on"}
        result["original_columns"] = [{c.key: getattr(obj, c.key) for c in inspect(self.Column).columns}
                                      for obj in self.session.query(self.Column).order_by(self.Column.id)
                                      if obj.table_id != 5 or obj.column_name in self.original_columns]
        for name in self.relation_names():
            rows = self.session.execute(text('SELECT * FROM public."' + name + '"')).mappings()
            result["relations"][name] = sorted((dict(row) for row in rows), key=digest)
        # Never expose protected metadata values in an exception or receipt.
        return digest(result)

    def fingerprint(self):
        fields = {p: cas_value(p, self.read(p)) for p in sorted(ALLOWED_PATHS)}
        return digest({"fields": fields, "protected": self.protected()})


def transact_postgres(store, direction):
    """Single-commit CAS, with database failures reduced to safe diagnostic codes."""
    try:
        return transact(store, store.bundle, direction)
    except UXConflict:
        raise
    except Exception as error:
        raise UXConflict(safe_database_error(error)) from None
