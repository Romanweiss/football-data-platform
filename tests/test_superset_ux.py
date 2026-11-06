"""Offline protocol tests; no Superset imports, network or private artifacts."""
from copy import deepcopy
import json
import unittest
from types import SimpleNamespace

from src.analytics.superset_ux import (
    ALLOWED_PATHS, UXConflict, display_mapping, load_bundle, require_fresh_mapping, transact,
)
from scripts.superset_ux_metadata import IsolatedMetadataStore
from scripts.build_superset_ux_layout import layout_revision
from src.analytics.superset_ux import BUNDLE_HASHES, hashes_for


class Store:
    def __init__(self, values):
        self.values = deepcopy(values)
        self.commits = 0
        self.fail = False
        self.alter_identity = False

    def begin(self):
        self.original = deepcopy(self.values)

    def read(self, path):
        return self.values[path]

    def write(self, path, value):
        self.values[path] = deepcopy(value)
        if self.fail:
            raise UXConflict("INJECTED_FAILURE")

    def flush(self):
        pass

    def protected(self):
        return "ids-uuids-owners" if not self.alter_identity or self.values == self.original else "changed"

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.values = self.original


class SupersetUXTests(unittest.TestCase):
    def setUp(self):
        self.changes = [{"path": p, "before": "old", "after": "new"} for p in sorted(ALLOWED_PATHS)]
        self.bundle = {"config-patch.json": self.changes}
        self.store = Store({c["path"]: "old" for c in self.changes})

    def test_exact_scope(self):
        self.assertEqual(len(ALLOWED_PATHS), 22)
        self.assertFalse(any("credentials" in p or "owners" in p or "/charts/1/" in p for p in ALLOWED_PATHS))

    def test_layout_revision_preserves_sql_identity_and_original(self):
        original = {"charts": {"13": {"params": {"guard": "same", "row_limit": 10000},
                    "query_context": {"queries": [{"where": "same"}], "form_data": {}}}},
                    "datasets": {"5": {"sql": "unchanged SQL"}}, "dashboards": {
                    "1": {"unchanged": True}, "2": {"metadata": {"native_filter": "same"}, "position": {
                        "summary": {"meta": {"chartId": 14, "height": 12}},
                        "kicks": {"meta": {"chartId": 13, "height": 20}},
                        "note": {"type": "MARKDOWN", "meta": {"height": 6, "code": "same"}}}}}}
        snapshot = deepcopy(original)
        new = layout_revision(original, "ux3-r2")
        self.assertEqual(original, snapshot)
        self.assertEqual(new["datasets"], original["datasets"])
        self.assertEqual(new["charts"]["13"]["query_context"]["queries"], original["charts"]["13"]["query_context"]["queries"])
        self.assertEqual(new["charts"]["13"]["params"]["row_limit"], 10000)
        self.assertEqual(new["dashboards"]["1"], original["dashboards"]["1"])
        self.assertEqual(new["dashboards"]["2"]["position"]["note"]["meta"]["height"], 20)
        self.assertEqual(new["charts"]["13"]["params"]["page_length"], 5)

    def test_revision_pins_do_not_replace_original(self):
        self.assertEqual(hashes_for("ux1"), BUNDLE_HASHES)
        self.assertEqual(hashes_for("ux3-r2")["before.json"], BUNDLE_HASHES["before.json"])
        self.assertNotEqual(hashes_for("ux3-r2")["candidate-config.json"], BUNDLE_HASHES["candidate-config.json"])
        with self.assertRaisesRegex(UXConflict, "UNKNOWN_REVISION"):
            load_bundle({}, "untrusted")

    def test_apply_rollback_exactly_one_commit_each(self):
        original = deepcopy(self.store.values)
        self.assertEqual(transact(self.store, self.bundle, "apply")["fields"], 22)
        self.assertEqual(self.store.commits, 1)
        transact(self.store, self.bundle, "rollback")
        self.assertEqual(self.store.values, original)
        self.assertEqual(self.store.commits, 2)

    def test_each_field_conflict_rolls_back_all(self):
        for path in ALLOWED_PATHS:
            store = Store({c["path"]: "old" for c in self.changes})
            store.values[path] = "operator edit"
            original = deepcopy(store.values)
            with self.assertRaisesRegex(UXConflict, "CAS_CONFLICT"):
                transact(store, self.bundle, "apply")
            self.assertEqual(store.values, original)
            self.assertEqual(store.commits, 0)

    def test_replay_not_silent(self):
        transact(self.store, self.bundle, "apply")
        with self.assertRaisesRegex(UXConflict, "CAS_CONFLICT"):
            transact(self.store, self.bundle, "apply")
        self.assertEqual(self.store.commits, 1)

    def test_partial_write_failure_is_atomic(self):
        self.store.fail = True
        original = deepcopy(self.store.values)
        with self.assertRaisesRegex(UXConflict, "INJECTED_FAILURE"):
            transact(self.store, self.bundle, "apply")
        self.assertEqual(self.store.values, original)
        self.assertEqual(self.store.commits, 0)

    def test_identity_change_fails_closed(self):
        self.store.alter_identity = True
        with self.assertRaisesRegex(UXConflict, "PROTECTED_IDENTITY_CHANGED"):
            transact(self.store, self.bundle, "apply")
        self.assertEqual(self.store.commits, 0)

    def test_wrong_bundle_rejected_before_json_parse(self):
        with self.assertRaises(UXConflict):
            load_bundle({"before.json": b"not-json"})

    def test_runtime_colors_preserved_without_allowing_native_filter_conflicts(self):
        path = "/dashboards/2/metadata"
        entry = next(c for c in self.changes if c["path"] == path)
        entry.update(before={"native": "old", "shared_label_colors": []},
                     after={"native": "new", "shared_label_colors": []})
        self.store.values[path] = {"native": "old", "shared_label_colors": ["runtime"]}
        transact(self.store, self.bundle, "apply")
        self.assertEqual(self.store.values[path], {"native": "new", "shared_label_colors": ["runtime"]})
        transact(self.store, self.bundle, "rollback")
        self.assertEqual(self.store.values[path], {"native": "old", "shared_label_colors": ["runtime"]})
        self.store.values[path]["native"] = "operator change"
        with self.assertRaisesRegex(UXConflict, "CAS_CONFLICT"):
            transact(self.store, self.bundle, "apply")

    def test_begin_failure_does_not_rollback_someone_elses_transaction(self):
        def begin():
            raise UXConflict("EXISTING_TRANSACTION")
        self.store.begin = begin
        self.store.rollback = lambda: self.fail("Unowned rollback")
        with self.assertRaisesRegex(UXConflict, "EXISTING_TRANSACTION"):
            transact(self.store, self.bundle, "apply")

    def test_invalid_direction_no_transaction(self):
        with self.assertRaisesRegex(UXConflict, "DIRECTION"):
            transact(self.store, self.bundle, "unsafe")

    def adapter(self, backend="sqlite", database="/tmp/superset-ux2.sqlite", active=False, fail=False):
        calls = []

        def execute(sql):
            calls.append(sql)
            if fail:
                raise RuntimeError("synthetic lock failure")

        session = SimpleNamespace(
            get_bind=lambda: SimpleNamespace(url=SimpleNamespace(get_backend_name=lambda: backend, database=database)),
            in_transaction=lambda: active,
            connection=lambda: SimpleNamespace(exec_driver_sql=execute),
            rollback=lambda: calls.append("ROLLBACK"),
        )
        bundle = {"before.json": {"datasets": {"5": {"columns": []}}}}
        return IsolatedMetadataStore(session, None, None, None, None, bundle), calls

    def test_adapter_denies_production_or_wrong_database(self):
        for backend, database in (("postgresql", "production"), ("sqlite", "/tmp/other.sqlite")):
            store, calls = self.adapter(backend, database)
            with self.assertRaisesRegex(UXConflict, "ISOLATED_METADATA_REQUIRED"):
                store.begin()
            self.assertEqual(calls, [])

    def test_adapter_existing_transaction_is_not_rolled_back(self):
        store, calls = self.adapter(active=True)
        with self.assertRaisesRegex(UXConflict, "EXISTING_TRANSACTION"):
            store.begin()
        self.assertEqual(calls, [])

    def test_adapter_lock_failure_rolls_back_only_own_attempt(self):
        store, calls = self.adapter(fail=True)
        with self.assertRaisesRegex(RuntimeError, "synthetic lock failure"):
            store.begin()
        self.assertEqual(calls, ["BEGIN IMMEDIATE", "ROLLBACK"])

    def test_adapter_acquires_writer_lock_before_cas(self):
        store, calls = self.adapter()
        store.begin()
        self.assertEqual(calls, ["BEGIN IMMEDIATE"])

    def records(self):
        return [{"match_display": f"Match {i}", "competition_id": 43, "season_id": 106, "match_id": i} for i in range(98)]

    def test_mapping_and_source_exact(self):
        records = self.records()
        mapping = {r["match_display"]: f"43/106/{r['match_id']}" for r in records}
        guard = "{% set lookup = " + json.dumps(mapping) + " %}"
        self.assertEqual(display_mapping(guard), mapping)
        require_fresh_mapping(mapping, records)

    def test_rename_date_score_changes_require_review(self):
        records = self.records()
        mapping = {r["match_display"]: f"43/106/{r['match_id']}" for r in records}
        for correction in ("Renamed team", "New date", "Corrected score"):
            changed = deepcopy(records)
            changed[0]["match_display"] = correction
            with self.assertRaisesRegex(UXConflict, "STALE_DISPLAY_MAPPING"):
                require_fresh_mapping(mapping, changed)

    def test_collision_and_reassignment_rejected(self):
        records = self.records()
        mapping = {r["match_display"]: f"43/106/{r['match_id']}" for r in records}
        records[0]["match_id"] = 1
        with self.assertRaises(UXConflict):
            require_fresh_mapping(mapping, records)


if __name__ == "__main__":
    unittest.main()
