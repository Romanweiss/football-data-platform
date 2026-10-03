"""SELECT-only validation of actual result casts/DQ and 008 view bodies. No DDL."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from bi_view_fixtures import synthetic_ctes
from src.analytics.gold_specs import RESULTS
from src.analytics.validation import expected_metrics, metric_expressions
from src.common.clickhouse import create_clickhouse_client

RESULT_SELECT = """SELECT toUInt32(43) competition_id, toUInt32(106) season_id, number+1 match_id,
    toDate('2022-12-01') match_date, '18:00:00.000' kick_off, toUInt16(1) competition_stage_id,
    'Test' competition_stage_name, toUInt32(10) home_team_id, 'Home' home_team_name,
    toUInt32(20) away_team_id, 'Away' away_team_name,
    toUInt16(if(number=0,2,if(number=3,3,1))) home_score,
    toUInt16(multiIf(number=0,0,number=2,2,number=3,3,1)) away_score,
    number>=2 went_to_extra_time, number=3 went_to_penalties,
    toUInt64(if(number=3,2,0)) home_shootout_attempts, toUInt64(if(number=3,2,0)) away_shootout_attempts,
    toUInt64(if(number=3,2,0)) home_shootout_goals, toUInt64(if(number=3,1,0)) away_shootout_goals,
    CAST(multiIf(number=1,NULL,number=2,20,10),'Nullable(UInt32)') winner_team_id,
    CAST(multiIf(number=1,NULL,number=2,'Away','Home'),'Nullable(String)') winner_team_name,
    multiIf(number=0,'REGULATION',number=1,'DRAW',number=2,'EXTRA_TIME','PENALTIES') result_method,
    multiIf(number=0,'2-0',number=1,'1-1',number=2,'1-2','3-3 (2-1 pens)') display_score
    FROM numbers(4)"""


class ResultSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.client=create_clickhouse_client()
    @classmethod
    def tearDownClass(cls): cls.client.close()

    def query(self,sql):
        self.assertNotIn('football.',sql)
        return self.client.query(sql,settings={'readonly':1}).result_rows

    def test_actual_insert_casts_and_dq_for_all_four_results(self):
        casts=', '.join(RESULTS.select_expressions)
        prefix=f'WITH raw AS ({RESULT_SELECT}), casted AS (SELECT {casts} FROM raw) '
        metrics=self.query(prefix+f'SELECT {metric_expressions(RESULTS)} FROM casted')[0]
        self.assertEqual(metrics,expected_metrics({'row_count':4,'match_count':4,'competition_id':43,'season_id':106},RESULTS))
        rows=self.query(prefix+'SELECT winner_team_id,result_method,display_score,toTypeName(match_date) FROM casted ORDER BY match_id')
        self.assertEqual(rows,[(10,'REGULATION','2-0','Date'),(None,'DRAW','1-1','Date'),(20,'EXTRA_TIME','1-2','Date'),(10,'PENALTIES','3-3 (2-1 pens)','Date')])

    def test_invalid_shootout_and_winner_detected_by_loader_dq(self):
        for field,value in [('home_shootout_goals','toUInt64(1)'),('away_shootout_goals','toUInt64(9)'),
                            ('winner_team_id','toNullable(toUInt32(999))'),('winner_team_name',"'Wrong'"),
                            ('display_score',"'7-5'"),('result_method',"'REGULATION'")]:
            invalid=' OR '.join(f'({p})' for p in RESULTS.invalid_predicates)
            sql=f'WITH raw AS ({RESULT_SELECT}), bad AS (SELECT * REPLACE ({value} AS {field}) FROM raw WHERE match_id=4) SELECT countIf({invalid}) FROM bad'
            with self.subTest(field=field): self.assertEqual(self.query(sql),[(1,)])

    def test_both_008_views_preserve_grain_and_read_authoritative_results(self):
        ctes,substitute=synthetic_ctes()
        # Keep original synthetic tables, replace only the view definitions.
        base=ctes.split(', test_team_view AS (')[0]
        results="""SELECT competition_id,season_id,match_id,match_id=2 went_to_extra_time,
            match_id=2 went_to_penalties,if(match_id=2,4,0) home_shootout_goals,if(match_id=2,2,0) away_shootout_goals,
            toNullable(if(match_id=3,away_team_id,home_team_id)) winner_team_id,
            toNullable(if(match_id=3,away_team_name,home_team_name)) winner_team_name,
            if(match_id=2,'PENALTIES','REGULATION') result_method,
            multiIf(match_id=1,'2-1',match_id=2,'0-0 (4-2 pens)','1-3') display_score FROM test_matches"""
        bodies=[s.split('\nAS\n',1)[1] for s in (ROOT/'infrastructure/clickhouse/migrations/008_enrich_bi_match_results.sql').read_text().split(';') if s.strip()]
        bodies=[substitute(s).replace('football.match_results','test_results') for s in bodies]
        prefix=base+', test_results AS ('+results+'), test_team_view AS ('+bodies[0]+'), test_player_view AS ('+bodies[1]+') '
        for name in ('test_team_view','test_player_view'):
            self.assertEqual(self.query(prefix+f'SELECT count() FROM {name}'),[(6,)])
            self.assertEqual(self.query(prefix+f'SELECT uniqExact(display_score),any(result_method),any(winner_team_id) FROM {name} WHERE match_id=2'),[(1,'PENALTIES',10)])
        self.assertEqual(self.query(prefix+'SELECT team_id,match_result FROM test_team_view WHERE match_id=2 ORDER BY team_id'),[(10,'W'),(20,'L')])

    def test_readonly_result_validation_sql(self):
        events="""SELECT toUInt32(43) competition_id,toUInt32(106) season_id,
            item.1 match_id,item.2 team_id,item.3 period,item.4 outcome_id,toString(idx) event_id
            FROM (SELECT arrayJoin(arrayZip(
                [(1,10,1,97),(2,10,1,97),(3,20,4,97),(4,10,4,97),
                 (4,10,5,97),(4,20,5,97),(4,10,5,97),(4,20,5,100)],
                [1,2,3,4,5,6,7,8])) pair, pair.1 item,pair.2 idx)"""
        prefix=f'WITH test_results AS ({RESULT_SELECT}), test_matches AS (SELECT * FROM test_results), test_events AS ({events}), test_shots AS (SELECT * FROM test_events) '
        mapping={'football.match_results':'test_results','football.matches':'test_matches','football.event_core':'test_events','football.shot_events':'test_shots'}
        checks=(ROOT/'scripts/check_clickhouse_match_results.sql').read_text().split(';')
        for sql in checks:
            if not sql.strip(): continue
            for original,replacement in mapping.items(): sql=sql.replace(original,replacement)
            with self.subTest(sql=sql[:100]):
                self.assertEqual(self.query(prefix + (sql % {"competition_id": 43, "season_id": 106}))[0][-1],0)


if __name__=='__main__': unittest.main(verbosity=2)
