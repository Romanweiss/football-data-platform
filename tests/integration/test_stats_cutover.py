"""SELECT-only Stage 4C tests using current audited v1 and virtual v2 CTEs. No writes."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.clickhouse import create_clickhouse_client
from src.analytics.gold_specs import SPECS, V2_SPECS
from src.analytics.stats_cutover import performance_query, query_rows, validate_deltas, validate_wc_totals, view_bodies
from src.gold.stats_snapshot import PINNED_STATS_INPUTS


class ShadowReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_clickhouse_client()
        cls.audit = json.loads((ROOT / 'docs/stage4b_shot_audit.json').read_text())
        cls.parameters = {name + '_build_id': value for name, value in PINNED_STATS_INPUTS.items()}

    @classmethod
    def tearDownClass(cls): cls.client.close()

    def test_exact_real_audit_deltas_against_select_only_v2_reconstruction(self):
        for name, spec in V2_SPECS.items():
            columns = ', '.join(column for column, _ in spec.columns)
            old = query_rows(self.client, f'SELECT {columns} FROM {SPECS[name].target} WHERE competition_id=43 AND season_id=106 AND gold_build_id=%(build_id)s',
                             {'build_id': self.audit['builds'][name]})
            new = query_rows(self.client, performance_query(spec), self.parameters)
            self.assertEqual(validate_deltas(old, new, spec=spec, audit=self.audit), self.audit[name]['affected_rows'])
            validate_wc_totals(new)
            self.assertEqual(sum(r['event_count'] for r in old)-sum(r['event_count'] for r in new), 106 if name=='team_match_stats' else 86)

    def test_cutover_full_public_schema_and_shootout_display_with_virtual_shadows(self):
        for (name, spec), body in zip(V2_SPECS.items(), view_bodies('v2'), strict=True):
            candidate = 'SELECT ' + ', '.join(spec.select_expressions) + ' FROM (' + performance_query(spec) + ')'
            virtual = 'WITH candidate AS (' + candidate + ') ' + body.replace(spec.target, 'candidate')
            result = self.client.query('SELECT * FROM (' + virtual + ') WHERE competition_id=43 AND season_id=106',
                                       parameters=self.parameters, settings={'readonly':1})
            expected = self.client.query('DESCRIBE TABLE football.bi_' + name, settings={'readonly':1}).result_rows
            self.assertEqual(list(zip(result.column_names, (kind.name for kind in result.column_types))), [(r[0],r[1]) for r in expected])
            rows = [dict(zip(result.column_names, r)) for r in result.result_rows]
            self.assertEqual(len(rows),128 if name=='team_match_stats' else 3244)
            self.assertEqual(sum(row['shot_count'] for row in rows),1453)
            for match, score in ((3869321,'2-2 (3-4 pens)'),(3869685,'3-3 (4-2 pens)')):
                selected = [row for row in rows if row['match_id']==match]
                self.assertTrue(selected)
                self.assertTrue(all(row['display_score']==score and row['result_method']=='PENALTIES' for row in selected))


if __name__ == '__main__': unittest.main(verbosity=2)
