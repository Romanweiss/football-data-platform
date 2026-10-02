"""SELECT-only checks of unapplied 012 against current serving; no DDL/S3."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.analytics import match_analysis as model
from src.analytics.validation import ClickHouseIntegrityError
from src.common.clickhouse import create_clickhouse_client


class MatchAnalysisReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_clickhouse_client()

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_candidate_full_schema_grain_values_nulls_counts_and_xg(self):
        summary = model.check_analysis(self.client, candidate=True)
        self.assertEqual(summary["rows"], {k: model.WC2022[k] for k in model.GRAINS})
        self.assertEqual(summary["shootout_matches"], 5)

    def test_lost_match_join_key_rejected(self):
        relations = model.candidate_relations()
        relations["shots"] = relations["shots"].replace("s.match_id = o.match_id", "1 = 1")
        with patch.object(model, "candidate_relations", return_value=relations), self.assertRaises(ClickHouseIntegrityError):
            model.check_analysis(self.client, candidate=True)

    def test_wrong_period_filter_cannot_pass(self):
        relations = model.candidate_relations()
        relations["shots"] = "(SELECT * FROM " + relations["shots"] + " WHERE period != 5)"
        with patch.object(model, "candidate_relations", return_value=relations), self.assertRaises(ClickHouseIntegrityError):
            model.check_analysis(self.client, candidate=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
