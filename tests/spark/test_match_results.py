"""Stage 4B synthetic Spark tests. No network/service/S3 access."""
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pyspark.sql import SparkSession, functions as F
from src.gold.statsbomb.match_results import build_match_results, validate_output
from src.gold.statsbomb.match_stats import build_match_stats
from src.gold.manifest import GoldIntegrityError
from src.gold import publish
from src.gold.build_identity import build_specification, calculate_build_id
from src.common.checksum import sha256_bytes


def fixtures(spark):
    matches = [(43,106,m,date(2022,12,m),'18:00:00.000',1,'Test',10,'Red',20,'Blue',h,a)
               for m,h,a in ((1,2,0),(2,1,1),(3,1,2),(4,3,3))]
    events = []
    shots = []
    def shot(match, team, period, outcome, xg):
        key = f"event-{len(events)}"
        player = team * 10
        events.append((43,106,match,key,team,player,period,16,True,True))
        shots.append((43,106,match,key,team,player,period,outcome,'Goal' if outcome==97 else 'Saved',xg))
    for match in (1,2,3,4):
        shot(match,10,1,97,0.1)
        shot(match,20,2,100,0.2)
    shot(3,20,3,97,0.3)
    shot(3,20,4,97,0.4)
    shot(4,10,4,97,0.4)
    for team,outcome in ((10,97),(20,97),(10,97),(20,100)):
        shot(4,team,5,outcome,0.7835)
    passes = [(43,106,4,'pass-shootout',10,100,5),(43,106,4,'pass-extra',20,200,3)]
    for comp, season, match, key, team, player, period in passes:
        events.append((comp,season,match,key,team,player,period,30,True,True))
    squads = [(43,106,m,t,'Red' if t==10 else 'Blue',p,f'Player {p}')
              for m in (1,2,3,4) for t in (10,20) for p in (t*10,t*10+1)]
    return {
        'matches':spark.createDataFrame(matches,'competition_id long, season_id long, match_id long, match_date date, kick_off string, competition_stage_id long, competition_stage_name string, home_team_id long, home_team_name string, away_team_id long, away_team_name string, home_score int, away_score int'),
        'event_core':spark.createDataFrame(events,'competition_id long, season_id long, match_id long, event_id string, team_id long, player_id long, period int, type_id int, under_pressure boolean, counterpress boolean'),
        'shot_events':spark.createDataFrame(shots,'competition_id long, season_id long, match_id long, event_id string, team_id long, player_id long, period int, outcome_id long, outcome_name string, statsbomb_xg double'),
        'pass_events':spark.createDataFrame(passes,'competition_id long, season_id long, match_id long, event_id string, team_id long, player_id long, period int'),
        'match_squads':spark.createDataFrame(squads,'competition_id long, season_id long, match_id long, team_id long, team_name string, player_id long, player_name string'),
    }


class MatchResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master('local[2]').appName('stage4b-synthetic')
            .config('spark.ui.enabled','false').config('spark.sql.shuffle.partitions','2').getOrCreate())
        cls.spark.sparkContext.setLogLevel('OFF')
        cls.frames = {name:frame.cache() for name,frame in fixtures(cls.spark).items()}
        cls.result, cls.counts = build_match_results(cls.frames, competition_id=43, season_id=106)

    @classmethod
    def tearDownClass(cls):
        cls.result.unpersist()
        for frame in cls.frames.values(): frame.unpersist()
        cls.spark.stop()

    def test_ordinary_draw_extra_time_and_penalties(self):
        a,b,c,d = self.result.orderBy('match_id').collect()
        self.assertEqual((a.result_method,a.display_score,a.winner_team_id),('REGULATION','2-0',10))
        self.assertEqual((b.result_method,b.winner_team_id,b.winner_team_name),('DRAW',None,None))
        self.assertEqual((c.result_method,c.winner_team_id,c.went_to_extra_time),('EXTRA_TIME',20,True))
        self.assertEqual((d.home_score,d.away_score,d.result_method,d.display_score),(3,3,'PENALTIES','3-3 (2-1 pens)'))
        self.assertEqual((d.home_shootout_attempts,d.away_shootout_attempts,d.home_shootout_goals,d.away_shootout_goals),(2,2,2,1))
        self.assertEqual((d.winner_team_id,d.winner_team_name),(10,'Red'))
        self.assertEqual((a.home_shootout_attempts,a.away_shootout_goals),(0,0))
        self.assertEqual(self.result.schema['match_date'].dataType.simpleString(),'date')
        self.assertEqual(self.result.schema['went_to_penalties'].dataType.simpleString(),'boolean')
        self.assertEqual(self.counts['row_count'],4)

    def test_deterministic_contents_schema_and_identity(self):
        frames = {name:frame.repartition(3) for name,frame in self.frames.items()}
        result,_ = build_match_results(frames,competition_id=43,season_id=106)
        self.addCleanup(result.unpersist)
        self.assertEqual(result.exceptAll(self.result).count(),0)
        self.assertEqual(self.result.exceptAll(result).count(),0)
        self.assertEqual(result.schema.json(),self.result.schema.json())
        def identity(frame):
            return calculate_build_id(build_specification(dataset='match_results',competition_id=43,season_id=106,
                transform_version='match_results_v1',input_fingerprint='a'*64,schema_sha256=sha256_bytes(frame.schema.json().encode())))
        self.assertEqual(identity(result),identity(self.result))

    def test_parquet_readback_preserves_nullable_winner_boolean_date_and_score(self):
        with TemporaryDirectory(prefix='match-results-test-') as directory:
            path=Path(directory)/'results'
            self.result.repartition(1).write.mode('errorifexists').option('compression','snappy').parquet(str(path))
            files=[{'object_key':str(part)} for part in path.glob('part-*.snappy.parquet')]
            self.assertEqual(len(files),1)
            with patch.object(publish,'s3a_uri',side_effect=lambda bucket,key:key):
                publish.validate_readback(self.spark,self.result,bucket='unused',files=files)
                with self.assertRaises(GoldIntegrityError):
                    publish.validate_readback(self.spark,self.result.withColumn('display_score',F.lit('wrong')),bucket='unused',files=files)

    def test_impossible_output_states_and_coverage_fail(self):
        for column,value in [('home_shootout_goals',999),('home_shootout_goals',1),('winner_team_id',99),
                             ('winner_team_name','Wrong'),('home_score',-1),('result_method','DRAW'),('display_score','7-5')]:
            bad = self.result.withColumn(column,F.when(F.col('match_id')==4,F.lit(value)).otherwise(F.col(column)))
            with self.subTest(column=column,value=value),self.assertRaises(GoldIntegrityError):
                validate_output(bad,self.frames['matches'],competition_id=43,season_id=106)
        for bad in (self.result.filter('match_id!=4'),self.result.unionByName(self.result.limit(1)),
                    self.result.withColumn('went_to_penalties',F.lit(False)),
                    self.result.withColumn('home_shootout_goals',F.lit(None).cast('long'))):
            with self.assertRaises(GoldIntegrityError):
                validate_output(bad,self.frames['matches'],competition_id=43,season_id=106)

    def test_shot_membership_and_period_mismatch_rejected(self):
        for bad in (self.frames['shot_events'].unionByName(self.frames['shot_events'].limit(1)),
                    self.frames['shot_events'].filter('period!=5'),
                    self.frames['shot_events'].withColumn('period',F.lit(1)),
                    self.frames['shot_events'].withColumn('team_id',F.lit(999))):
            with self.assertRaises(GoldIntegrityError):
                build_match_results({**self.frames,'shot_events':bad},competition_id=43,season_id=106)

    def test_v2_excludes_only_period5_from_all_metrics_preserves_v1(self):
        for dataset in ('team_match_stats','player_match_stats'):
            original,_ = build_match_stats(self.frames,dataset=dataset,competition_id=43,season_id=106)
            result,_ = build_match_stats(self.frames,dataset=dataset,competition_id=43,season_id=106,transform_version=dataset+'_v2')
            self.addCleanup(original.unpersist)
            self.addCleanup(result.unpersist)
            def total(frame,name): return frame.agg(F.sum(name)).first()[0]
            self.assertEqual(total(original,'shot_count')-total(result,'shot_count'),4)
            self.assertEqual(total(original,'shot_goals')-total(result,'shot_goals'),3)
            self.assertAlmostEqual(total(original,'shot_xg')-total(result,'shot_xg'),4*0.7835)
            for name in ('event_count','under_pressure_events','counterpress_events'):
                self.assertEqual(total(original,name)-total(result,name),5)
            self.assertEqual(total(original,'pass_attempts')-total(result,'pass_attempts'),1)
            extra = result.filter('match_id=3 AND team_id=20').agg(F.sum('shot_count'),F.sum('shot_xg')).first()
            self.assertEqual(extra[0],3)
            self.assertAlmostEqual(extra[1],0.9)
            self.assertEqual(result.count(),original.count())
            self.assertEqual(result.schema.json(),original.schema.json())


if __name__=='__main__':
    unittest.main(verbosity=2)
