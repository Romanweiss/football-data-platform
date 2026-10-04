"""Offline metadata contracts; no Superset imports, secrets or service calls."""
from copy import deepcopy
import unittest

from src.analytics.superset_safety import (
    DATASETS, DEFAULT_MATCH, IDENTITY_SQL, MATCH_GUARD, OVERVIEW, MATCH_CHARTS,
    patch_chart, patch_match_filter, require_contract, WC_CONTEXT,
)


class SupersetSafetyTests(unittest.TestCase):
    def test_wc_filter_preserves_native_and_analytical_settings(self):
        params = {"metrics": ["sum_xg"], "adhoc_filters": [{"subject": "match_date", "comparator": "No filter"}]}
        qc = {"queries": [{"extras": {"where": "is_shootout = 0"}}], "form_data": deepcopy(params)}
        original = deepcopy((params, qc))
        p, q = patch_chart(params, qc, WC_CONTEXT, "guard")
        self.assertEqual((params, qc), original)
        self.assertEqual(p["metrics"], ["sum_xg"])
        self.assertEqual(p["adhoc_filters"][0], params["adhoc_filters"][0])
        self.assertEqual(q["queries"][0]["extras"]["where"], "(is_shootout = 0) AND (competition_id = 43 AND season_id = 106)")
        self.assertEqual(q["form_data"]["adhoc_filters"], p["adhoc_filters"])

    def test_patch_is_idempotent(self):
        p, q = patch_chart({}, {"queries": [{"extras": {}}], "form_data": {}}, MATCH_GUARD, "guard")
        self.assertEqual(patch_chart(p, q, MATCH_GUARD, "guard"), (p, q))

    def test_selector_all_charts_full_key_and_fail_closed_default(self):
        metadata = {"native_filter_configuration": [{"name": "Match", "controlValues": {}, "id": "preserved"}], "layout": "preserved"}
        updated = patch_match_filter(metadata)
        f = updated["native_filter_configuration"][0]
        self.assertEqual(f["id"], "preserved")
        self.assertEqual(updated["layout"], "preserved")
        self.assertEqual(f["chartsInScope"], list(range(9, 17)))
        self.assertEqual(f["targets"][0]["column"]["name"], "match_identity")
        self.assertFalse(f["controlValues"]["creatable"])
        self.assertFalse(f["controlValues"]["multiSelect"])
        self.assertEqual(f["defaultDataMask"]["extraFormData"]["filters"][0]["val"], [DEFAULT_MATCH])
        for col in ("competition_id", "season_id", "match_id", "match_label"):
            self.assertIn(col, IDENTITY_SQL)
        self.assertEqual(patch_match_filter(updated), updated)

    def test_exact_chart_inventory(self):
        self.assertEqual(set(OVERVIEW), set(range(1, 9)))
        self.assertEqual(set(MATCH_CHARTS), set(range(9, 17)))
        self.assertEqual(len(set(MATCH_CHARTS.values())), 7)

    def test_rejects_unexpected_selector_configuration(self):
        for filters in ([], [{"name": "Other"}], [{"name": "Match"}, {"name": "Extra"}]):
            with self.assertRaises(ValueError):
                patch_match_filter({"native_filter_configuration": filters})

    def valid_contract(self):
        charts = {}
        for cid, did in {**OVERVIEW, **MATCH_CHARTS}.items():
            expression = WC_CONTEXT if cid in OVERVIEW else MATCH_GUARD
            p, q = patch_chart({}, {"queries": [{"extras": {}}], "form_data": {}}, expression, "guard")
            charts[cid] = {"dataset": did, "params": p, "query_context": q}
        datasets = {did: {"name": name, "schema": "football", "sql": None,
                          "predicate": WC_CONTEXT if did in (2, 3) else None,
                          "identity_expression": IDENTITY_SQL if did not in (2, 3) else None}
                    for did, name in DATASETS.items()}
        metadata = patch_match_filter({"native_filter_configuration": [{"name": "Match", "controlValues": {}}]})
        return charts, datasets, metadata

    def test_complete_live_contract_is_accepted(self):
        require_contract(*self.valid_contract())

    def test_any_missing_wc_guard_is_rejected(self):
        for cid in OVERVIEW:
            charts, datasets, metadata = self.valid_contract()
            charts[cid]["params"]["adhoc_filters"] = []
            with self.assertRaises(ValueError):
                require_contract(charts, datasets, metadata)

    def test_stale_saved_query_guard_is_rejected(self):
        charts, datasets, metadata = self.valid_contract()
        charts[15]["query_context"]["queries"][0]["extras"]["where"] = ""
        with self.assertRaises(ValueError):
            require_contract(charts, datasets, metadata)

    def test_missing_identity_or_excluded_scope_is_rejected(self):
        charts, datasets, metadata = self.valid_contract()
        datasets[10]["identity_expression"] = "match_label"
        with self.assertRaises(ValueError):
            require_contract(charts, datasets, metadata)
        charts, datasets, metadata = self.valid_contract()
        metadata["native_filter_configuration"][0]["scope"]["excluded"] = [15]
        with self.assertRaises(ValueError):
            require_contract(charts, datasets, metadata)
