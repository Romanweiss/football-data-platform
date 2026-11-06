"""Isolated-only SQLAlchemy adapter for the pinned 22-field CAS protocol.

Not a live apply CLI. No credentials/RBAC assignments or full-object imports.
The deliberately narrow metadata database gate must not be bypassed for live use.
"""
from copy import deepcopy
import json

from src.analytics.superset_ux import check

COLUMN_FIELDS = ("column_name", "expression", "type", "groupby", "filterable", "is_dttm", "verbose_name")
MODEL_FIELDS = {
    "charts": {"params": "params", "query_context": "query_context", "description": "description"},
    "datasets": {"sql": "sql", "columns": "columns"},
    "dashboards": {"metadata": "json_metadata", "position": "position_json"},
}


class IsolatedMetadataStore:
    def __init__(self, session, Chart, Dataset, Dashboard, Column, bundle):
        self.session = session
        self.models = {"charts": Chart, "datasets": Dataset, "dashboards": Dashboard}
        self.Column = Column
        self.original_columns = [c["column_name"] for c in bundle["before.json"]["datasets"]["5"]["columns"]]

    def begin(self):
        url = self.session.get_bind().url
        check(url.get_backend_name() == "sqlite" and url.database in
              ("/tmp/superset-ux2.sqlite", "/tmp/superset-ux3.sqlite"), "ISOLATED_METADATA_REQUIRED")
        check(not self.session.in_transaction(), "EXISTING_TRANSACTION")
        # SQLite has no SELECT FOR UPDATE; take its writer lock before CAS reads.
        try:
            self.session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        except Exception:
            self.session.rollback()  # Only our newly acquired transaction.
            raise

    def object(self, path):
        _, kind, identifier, field = path.split("/")
        check(kind in MODEL_FIELDS and field in MODEL_FIELDS[kind], "FIELD_NOT_ALLOWED")
        obj = self.session.get(self.models[kind], int(identifier))
        check(obj is not None, "OBJECT_MISSING")
        return obj, field, MODEL_FIELDS[kind][field]

    def columns(self, obj):
        by_name = {c.column_name: c for c in obj.columns}
        names = self.original_columns + [n for n in ("match_display", "shootout_status") if n in by_name]
        check(set(names) == set(by_name), "COLUMN_SCOPE_CONFLICT")
        return [{f: getattr(by_name[n], f) for f in COLUMN_FIELDS} for n in names]

    def read(self, path):
        obj, field, attribute = self.object(path)
        if field == "columns":
            return self.columns(obj)
        value = getattr(obj, attribute)
        return json.loads(value or "{}") if field in ("params", "query_context", "metadata", "position") else value

    def write(self, path, value):
        obj, field, attribute = self.object(path)
        if field == "columns":
            existing = {c.column_name: c for c in obj.columns}
            target = {c["column_name"]: c for c in value}
            for name in self.original_columns:
                check({f: getattr(existing[name], f) for f in COLUMN_FIELDS} == target[name], "ORIGINAL_COLUMN_CHANGED")
            for name in ("match_display", "shootout_status"):
                if name in target and name not in existing:
                    obj.columns.append(self.Column(**deepcopy(target[name])))
                elif name not in target and name in existing:
                    column = existing[name]
                    obj.columns.remove(column)
                    self.session.delete(column)
            return
        setattr(obj, attribute, json.dumps(value) if field in ("params", "query_context", "metadata", "position") else value)

    def protected(self):
        result = {}
        for kind, model in self.models.items():
            for obj in self.session.query(model).order_by(model.id):
                row = [obj.id, str(obj.uuid), sorted(u.id for u in obj.owners)]
                if kind == "datasets":
                    row.append(sorted((c.column_name, c.id) for c in obj.columns
                                      if obj.id != 5 or c.column_name in self.original_columns))
                result[f"{kind}/{obj.id}"] = row
        return result

    def flush(self):
        self.session.flush()

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()
