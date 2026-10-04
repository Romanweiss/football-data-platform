"""Run in Superset image, --network none; actual Jinja/ClickHouse literal quoting."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy.dialects import registry
from superset.jinja_context import WhereInMacro
from src.analytics.superset_safety import MATCH_GUARD


class SelectedMatchTemplateTests(unittest.TestCase):
    def render(self, filters):
        env = SandboxedEnvironment()
        env.filters["where_in"] = WhereInMacro(registry.load("clickhousedb")())
        return env.from_string(MATCH_GUARD).render(get_filters=lambda col: filters)

    def test_empty_is_fail_closed(self):
        self.assertEqual(self.render([]), "0 = 1")

    def test_one_full_identity_allowed(self):
        sql = self.render([{"op": "IN", "val": ["43/106/3869685 | same label"]}])
        self.assertIn("43/106/3869685 | same label", sql)
        self.assertNotIn("0 = 1", sql)

    def test_multiple_values_and_multiple_filters_fail_closed(self):
        for filters in ([{"op": "IN", "val": ["a", "b"]}],
                        [{"op": "IN", "val": ["a"]}, {"op": "IN", "val": ["b"]}]):
            self.assertEqual(self.render(filters), "0 = 1")

    def test_inverse_or_empty_filter_fail_closed(self):
        for op in ("NOT IN", "LIKE", "IS NULL"):
            self.assertEqual(self.render([{"op": op, "val": ["a"]}]), "0 = 1")
        self.assertEqual(self.render([{"op": "IN", "val": []}]), "0 = 1")

    def test_identical_labels_in_different_contexts_have_distinct_predicates(self):
        first = self.render([{"op": "IN", "val": ["43/106/1 | same"]}])
        second = self.render([{"op": "IN", "val": ["9/281/1 | same"]}])
        self.assertNotEqual(first, second)

    def test_sql_injection_text_is_quoted_not_interpolated(self):
        value = "43/106/1 | O'Brien'); SELECT 1 --"
        sql = self.render([{"op": "IN", "val": [value]}])
        self.assertIn("O''Brien", sql)
        self.assertIn("Brien''); SELECT 1 --'", sql)


if __name__ == "__main__":
    unittest.main()
