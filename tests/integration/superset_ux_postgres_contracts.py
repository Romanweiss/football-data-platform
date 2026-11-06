"""Explicit ephemeral PostgreSQL/Superset 6 contracts; never auto-connect on import.

run_contracts requires a preconfigured isolated Flask app in a network-none test
namespace. It seeds only a fresh database; explicit resume never overwrites rows.
No production connections, readers, credentials, migrations or chart queries.
"""
from copy import deepcopy
import json

from scripts.superset_ux_postgres import (
    GUARD_TABLE, TARGET_MARKER, IsolatedPostgresMetadataStore, digest, require_target, transact_postgres,
)
from src.analytics.superset_ux import ALLOWED_PATHS, UXConflict, cas_value, load_bundle


def run_contracts(app, raw, resume_existing=False):
    from sqlalchemy import inspect, text
    from sqlalchemy.orm import sessionmaker
    from superset import db, security_manager
    from superset.models.core import Database
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard
    from superset.connectors.sqla.models import SqlaTable, TableColumn

    require_target(db.engine.url)
    bundle = load_bundle(raw, "ux3-r2")
    before = bundle["before.json"]
    if db.session.query(Slice).count():
        assert resume_existing, "FRESH_DATABASE_REQUIRED"
        assert db.session.execute(text("SELECT marker FROM public.ux4_target_guard WHERE id=1")).scalar() == TARGET_MARKER
        db.session.rollback()
    else:
        assert GUARD_TABLE not in inspect(db.engine).get_table_names(), "NO_OVERWRITE"
        role = security_manager.add_role("UX4 synthetic role")
        owner = security_manager.find_user(username="ux4-owner") or security_manager.add_user(
            username="ux4-owner", first_name="Synthetic", last_name="Owner",
            email="ux4@example.invalid", role=role, password="synthetic-test-only")
        database = Database(id=1, database_name="UX4 synthetic unconnected database",
                            sqlalchemy_uri="sqlite://", allow_dml=False)
        db.session.add(database)
        for did, value in before["datasets"].items():
            table = SqlaTable(id=int(did), table_name=value["name"], schema=value["schema"], sql=value["sql"],
                              database=database, fetch_values_predicate=value["predicate"], owners=[owner])
            table.columns = [TableColumn(**column) for column in value["columns"]]
            db.session.add(table)
        db.session.flush()
        charts = {}
        for cid, value in before["charts"].items():
            chart = Slice(id=int(cid), slice_name=value["name"], datasource_id=value["dataset"], datasource_type="table",
                          viz_type=value["viz_type"], params=json.dumps(value["params"]),
                          query_context=json.dumps(value["query_context"]), description=value["description"], owners=[owner])
            charts[int(cid)] = chart
            db.session.add(chart)
        for did, value in before["dashboards"].items():
            db.session.add(Dashboard(id=int(did), dashboard_title=value["title"], json_metadata=json.dumps(value["metadata"]),
                                     position_json=json.dumps(value["position"]), css=value["css"], published=value["published"],
                                     owners=[owner], slices=[charts[i] for i in value["chart_ids"]]))
        db.session.execute(text("CREATE TABLE public.ux4_target_guard (id integer PRIMARY KEY CHECK (id=1), marker text NOT NULL)"))
        db.session.execute(text("INSERT INTO public.ux4_target_guard VALUES (1, :marker)"), {"marker": TARGET_MARKER})
        db.session.commit()
    db.session.remove()
    Session = sessionmaker(bind=db.engine, expire_on_commit=False)
    results = {}

    def store(session, fingerprint="0" * 64):
        return IsolatedPostgresMetadataStore(session, Slice, SqlaTable, Dashboard, TableColumn, raw, fingerprint)

    def reviewed(session):
        value = store(session).fingerprint()
        session.rollback()
        return value

    def snapshot(session):
        result = {}
        # Compare complete rows but not ORM audit timestamps, nor nontransactional sequences.
        for name in inspect(session.connection()).get_table_names(schema="public"):
            rows = session.execute(text('SELECT * FROM public."' + name + '"')).mappings()
            result[name] = sorted(({k: v for k, v in row.items() if k != "changed_on"}
                                   for row in rows), key=digest)
        session.rollback()
        return result

    def assert_fields(session, direction):
        expected = bundle["candidate-config.json" if direction == "new" else "before.json"]
        reader = store(session)
        for path in ALLOWED_PATHS:
            _, kind, identifier, field = path.split("/")
            assert cas_value(path, reader.read(path)) == cas_value(path, expected[kind][identifier][field]), "SEMANTIC_FIELDS"
        session.rollback()

    def reject(operation, codes):
        try:
            operation()
        except UXConflict as error:
            assert str(error) in codes, "UNEXPECTED_ERROR_CODE"
            return str(error)
        raise AssertionError("EXPECTED_CONFLICT")

    with Session() as session:
        assert_fields(session, "old")
        baseline = snapshot(session)
        original = reviewed(session)
        result = transact_postgres(store(session, original), "apply")
        assert result["commits"] == 1 and result["fields"] == 22, "SINGLE_COMMIT"
        assert_fields(session, "new")
        current = reviewed(session)
        results["clean_apply"] = result
        results["replay"] = reject(lambda: transact_postgres(store(session, current), "apply"), {"CAS_CONFLICT"})
        assert reviewed(session) == current, "REPLAY_MUTATION"
        result = transact_postgres(store(session, current), "rollback")
        assert_fields(session, "old")
        assert reviewed(session) == original, "ROUND_TRIP_FINGERPRINT"
        assert snapshot(session) == baseline, "UNRELATED_METADATA_CHANGED"
        results["rollback"] = result
        results["old_validator"] = "PASS: all 22 fields, full metadata/RBAC/owners/IDs round trip"
        results["before_fingerprint"] = original
        results["candidate_fingerprint"] = current

        # Failure after actual UPDATE/INSERT statements, not just before begin.
        class Broken(IsolatedPostgresMetadataStore):
            def flush(self):
                super().flush()
                raise RuntimeError("synthetic-database-detail-must-not-escape")
        broken = Broken(session, Slice, SqlaTable, Dashboard, TableColumn, raw, original)
        results["mid_write_failure"] = reject(lambda: transact_postgres(broken, "apply"), {"POSTGRES_TRANSACTION_FAILURE"})
        assert snapshot(session) == baseline, "PARTIAL_WRITE"

        with Session() as operator:
            operator.execute(text("UPDATE slices SET description = 'synthetic operator edit' WHERE id=9"))
            operator.commit()
        edited = snapshot(session)
        results["operator_edit_before_apply"] = reject(lambda: transact_postgres(store(session, original), "apply"),
                                                       {"METADATA_FINGERPRINT_CONFLICT"})
        assert snapshot(session) == edited, "OPERATOR_EDIT_LOST"
        with Session() as operator:
            operator.execute(text("UPDATE slices SET description = :value WHERE id=9"),
                             {"value": before["charts"]["9"]["description"]})
            operator.commit()

        # An edit on Overview (outside all 22 patch paths) must also invalidate the fingerprint.
        with Session() as operator:
            operator.execute(text("UPDATE slices SET params = '{}' WHERE id=1"))
            operator.commit()
        results["unowned_metadata_edit"] = reject(lambda: transact_postgres(store(session, original), "apply"),
                                                  {"METADATA_FINGERPRINT_CONFLICT"})
        with Session() as operator:
            operator.execute(text("UPDATE slices SET params = :value WHERE id=1"),
                             {"value": json.dumps(before["charts"]["1"]["params"])})
            operator.commit()

        # Row lock blocks an ordinary operator UPDATE even without using our adapter.
        locked = store(session, original)
        locked.begin()
        with Session() as operator:
            operator.execute(text("SET LOCAL lock_timeout='150ms'"))
            try:
                operator.execute(text("UPDATE slices SET description='synthetic race' WHERE id=9"))
            except Exception as error:
                assert getattr(error.orig, "pgcode", None) == "55P03", "ROW_LOCK_NOT_ENFORCED"
                results["concurrent_operator_blocked"] = "55P03"
                operator.rollback()
            else:
                raise AssertionError("OPERATOR_NOT_BLOCKED")
        session.rollback()

        # Reverse race: an existing editor holds a row lock. Our writer fails closed.
        with Session() as operator:
            operator.execute(text("UPDATE slices SET description='synthetic held edit' WHERE id=9"))
            results["existing_operator_lock"] = reject(lambda: transact_postgres(store(session, original), "apply"),
                                                       {"POSTGRES_LOCK_CONFLICT"})
            operator.rollback()
        assert snapshot(session) == baseline, "LOCK_FAILURE_MUTATION"

        # Owner and RBAC association changes invalidate the reviewed fingerprint.
        with Session() as operator:
            operator.execute(text("INSERT INTO ab_role (id,name) VALUES (987654321,'synthetic concurrent role')"))
            operator.commit()
        results["rbac_change"] = reject(lambda: transact_postgres(store(session, original), "apply"),
                                         {"METADATA_FINGERPRINT_CONFLICT"})
        with Session() as operator:
            operator.execute(text("DELETE FROM ab_role WHERE name='synthetic concurrent role'"))
            operator.commit()

        with Session() as operator:
            memberships = [dict(row) for row in operator.execute(
                text("SELECT * FROM slice_user WHERE slice_id=9")).mappings()]
            operator.execute(text("DELETE FROM slice_user WHERE slice_id=9"))
            operator.commit()
        results["owner_change"] = reject(lambda: transact_postgres(store(session, original), "apply"),
                                          {"METADATA_FINGERPRINT_CONFLICT"})
        with Session() as operator:
            table = Slice.owners.property.secondary
            operator.execute(table.insert(), memberships)
            operator.commit()

        with Session() as operator:
            operator.execute(text("UPDATE ux4_target_guard SET marker='synthetic wrong marker' WHERE id=1"))
            operator.commit()
        results["wrong_target_marker"] = reject(lambda: transact_postgres(store(session, original), "apply"),
                                                 {"ISOLATED_POSTGRES_MARKER_REQUIRED"})
        with Session() as operator:
            operator.execute(text("UPDATE ux4_target_guard SET marker=:marker WHERE id=1"), {"marker": TARGET_MARKER})
            operator.commit()

        transact_postgres(store(session, original), "apply")
        candidate = reviewed(session)
        with Session() as operator:
            operator.execute(text("UPDATE slices SET description='synthetic rollback edit' WHERE id=13"))
            operator.commit()
        edited = snapshot(session)
        results["rollback_operator_conflict"] = reject(lambda: transact_postgres(store(session, candidate), "rollback"),
                                                       {"METADATA_FINGERPRINT_CONFLICT"})
        assert snapshot(session) == edited, "ROLLBACK_LOST_OPERATOR_EDIT"
        with Session() as operator:
            operator.execute(text("UPDATE slices SET description=:value WHERE id=13"),
                             {"value": bundle["candidate-config.json"]["charts"]["13"]["description"]})
            operator.commit()
        transact_postgres(store(session, candidate), "rollback")
        assert_fields(session, "old")
        assert snapshot(session) == baseline, "FINAL_METADATA_CHANGED"
        results["final_contract"] = "old"
        results["full_metadata_round_trip"] = "PASS (audit changed_on and sequences excluded)"
        results["status"] = "PASS"
        results["models"] = {"charts": 16, "datasets": 12, "dashboards": 2}
        results["new_source_records"] = 0
    return deepcopy(results)
